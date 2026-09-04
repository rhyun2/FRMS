# FRMS를 AWS EC2에 배포하기

20명 규모(비기능 요구사항 근거, [PRD 8절](../docs/PRD.md#8-비기능-요구사항))에 맞춘
**EC2 단일 인스턴스 + nginx + systemd** 구성이다. 무중단 배포·수평 확장은 요구하지
않으므로 이 이상의 구성(ALB, Auto Scaling, ECS 등)은 과잉이다.

```
사용자 브라우저
      │ HTTPS (443)
      ▼
  [nginx] ── 리버스 프록시, TLS 종료, /static 서빙
      │ 127.0.0.1:8000
      ▼
  [gunicorn + uvicorn worker] ── FastAPI 앱 (systemd로 상시 구동)
      │
      ▼
  [SQLite 파일] (EBS 볼륨, 정기 백업) 또는 RDS PostgreSQL
```

이 디렉토리의 파일:

| 파일 | 용도 |
|---|---|
| `frms.service` | systemd 유닛. `/etc/systemd/system/frms.service` 로 설치 |
| `nginx.conf` | nginx 사이트 설정. `/etc/nginx/sites-available/frms` 로 설치 |
| `backup-to-s3.cron` | SQLite 백업 크론 (SQLite로 운영할 때만) |

---

## 1. EC2 인스턴스 생성

1. **EC2 → 인스턴스 시작**, AMI: **Ubuntu Server 24.04 LTS**
2. 인스턴스 유형: **t3.small** (2GiB RAM — t3.micro는 uvicorn+nginx+SQLite 동시 구동에 빠듯함)
3. **키 페어 생성** → `.pem` 다운로드 → 로컬에 안전하게 보관
4. **보안 그룹** 인바운드 규칙:

   | 유형 | 포트 | 소스 |
   |---|---|---|
   | SSH | 22 | 내 IP만 (0.0.0.0/0 금지) |
   | HTTP | 80 | 0.0.0.0/0 |
   | HTTPS | 443 | 0.0.0.0/0 |

5. 스토리지 20GB gp3, **"종료 시 삭제" 옵션은 꺼둔다** (SQLite로 운영 시 데이터 보존을 위해)
6. **탄력적 IP**를 할당해 인스턴스에 연결 (재부팅 시 IP가 바뀌지 않도록)

## 2. SSH 접속

```bash
chmod 400 frms-key.pem
ssh -i frms-key.pem ubuntu@<탄력적_IP>
```

## 3. 서버 기본 설정

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git nginx build-essential software-properties-common

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

### Python 3.12 확인 및 설치

FRMS는 `python3.12` 실행 파일로 가상환경을 만든다(4절). AMI가 실제로 어떤 버전인지
가정하지 않고 **없으면 설치**하는 방식으로 확인한다 — "Ubuntu 24.04라 필요 없다"는
가정은 콘솔에서 다른 이미지를 고르는 순간 깨지고, 그때 4절에서 원인을 알아보기 어려운
`python3.12: command not found` → `pip: command not found` 연쇄 오류로 나타난다.

```bash
if ! command -v python3.12 >/dev/null 2>&1; then
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install -y python3.12 python3.12-venv python3.12-dev
fi

python3.12 --version   # 3.12.x 가 출력되어야 4절로 진행한다
```

이 명령이 버전을 출력하지 않으면 4절을 실행하지 않는다.

## 4. 애플리케이션 배포

전용 시스템 계정으로 돌린다 (`ubuntu` 계정으로 직접 실행하지 않는다):

```bash
sudo useradd --system --create-home --shell /bin/bash frms
sudo mkdir -p /opt/frms && sudo chown frms:frms /opt/frms

sudo -u frms -H bash -c '
  set -euo pipefail

  # PR #1이 머지되기 전까지는 main 에 앱 코드가 없다(빈 초기 커밋뿐).
  # 머지 후에는 이 한 줄만 main 으로 바꾼다.
  BRANCH="claude/iot-feature-request-prd-zarubq"

  cd /opt/frms

  # 재실행에도 안전하도록: 이미 클론돼 있으면 clone 대신 fetch 한다.
  if [ -d .git ]; then
    git fetch origin
  else
    git clone https://github.com/rhyun2/FRMS.git .
  fi
  git checkout "$BRANCH"
  git pull origin "$BRANCH"

  command -v python3.12 >/dev/null 2>&1 || {
    echo "python3.12가 없습니다. 3절의 Python 설치 단계를 먼저 실행하세요." >&2
    exit 1
  }

  python3.12 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  pip install gunicorn

  [ -f .env ] || cp .env.example .env
'
```

`set -euo pipefail`이 없으면 앞 단계가 실패해도 스크립트가 계속 진행되며 이후 명령이
줄줄이 실패해, 정작 원인(첫 실패)이 아니라 그 여파만 잔뜩 보게 된다. `python3.12`가
없어서 venv 생성이 실패했을 때 `pip: command not found`가 세 줄 더 쏟아지는 것이
그 예다 — 진짜 원인은 하나뿐이었다.

### `.env` 설정

```bash
sudo nano /opt/frms/.env
```

```ini
DATABASE_URL=sqlite:///./frms.db
SESSION_SECRET=<openssl rand -hex 32 로 생성>
```

```bash
openssl rand -hex 32   # SESSION_SECRET 값 생성
```

**Entra ID SSO**(오픈 이슈 O3)가 준비됐다면 `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` /
`ENTRA_CLIENT_SECRET` / `ENTRA_REDIRECT_URI`도 채운다. 셋을 모두 채우면 개발용 로컬
로그인이 자동으로 닫힌다 (`app/config.py`의 `sso_enabled`).

> **인터넷에 노출하기 전 인증 방식을 반드시 결정한다.** Entra ID 연동 전까지는 보안
> 그룹의 80/443 소스를 사무실 IP·VPN 대역으로 좁혀 두는 것을 권장한다 — 개발용 로컬
> 로그인은 계정 목록에서 누구나 골라 로그인할 수 있다.

### DB 초기화

```bash
sudo -u frms -H bash -c '
  set -euo pipefail
  cd /opt/frms && source .venv/bin/activate
  python -m app.seed
'
```

운영 전환 시에는 데모 사용자 대신 관리자 1명만 만들고, 나머지는 `/admin/users`
화면 또는 실제 Entra 로그인(최초 로그인 시 자동 생성)으로 채우는 편이 낫다.

## 5. systemd 서비스 설치

```bash
sudo cp deploy/frms.service /etc/systemd/system/frms.service
sudo systemctl daemon-reload
sudo systemctl enable --now frms
sudo systemctl status frms
```

로그: `sudo journalctl -u frms -f`

`--workers 2`는 2코어 인스턴스 기준이다. 코어 수가 다르면
`(2 × CPU 코어) + 1` 정도로 `deploy/frms.service`의 `--workers` 값을 조정한다.

## 6. nginx 설치

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/frms
sudo sed -i 's/your-domain.example.com/<실제 도메인 또는 탄력적 IP>/' \
  /etc/nginx/sites-available/frms
sudo ln -s /etc/nginx/sites-available/frms /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

`http://<탄력적_IP>` 로 접속해 로그인 화면이 뜨는지 확인한다.

## 7. HTTPS (도메인이 있는 경우)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example.com
```

인증서 자동 갱신 타이머까지 함께 등록된다.

## 8. 데이터베이스: SQLite로 시작 → 필요 시 RDS로 전환

MVP·20명 규모는 SQLite로 충분하다. 다만 인스턴스가 사라지면 데이터도 사라지므로:

- EBS "종료 시 삭제" 옵션을 꺼둔다 (1절에서 이미 설정)
- `deploy/backup-to-s3.cron`으로 정기 백업

```bash
sudo cp deploy/backup-to-s3.cron /etc/cron.d/frms-backup
sudo sed -i 's/<버킷명>/실제-버킷-이름/' /etc/cron.d/frms-backup
sudo chmod 644 /etc/cron.d/frms-backup
```

(사전에 인스턴스에 S3 쓰기 IAM 역할 부여 또는 `sudo -u frms aws configure` 필요)

Phase 2 이후 다중 가용영역이 필요해지면 코드 변경 없이 `.env` 한 줄만 바꿔 전환한다:

```ini
DATABASE_URL=postgresql+psycopg://frms:<비밀번호>@<RDS 엔드포인트>:5432/frms
```

```bash
sudo -u frms /opt/frms/.venv/bin/pip install "psycopg[binary]"
sudo systemctl restart frms
```

## 9. 배포 갱신

```bash
sudo -u frms -H bash -c '
  set -euo pipefail
  BRANCH="claude/iot-feature-request-prd-zarubq"   # PR #1 머지 후 main 으로
  cd /opt/frms
  git fetch origin
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
  source .venv/bin/activate
  pip install -r requirements.txt
'
sudo systemctl restart frms
```

무중단이 필요 없는 규모라 재시작 한 번으로 충분하다.

## 10. 최종 점검 체크리스트

- [ ] `https://<도메인>/` 접속 시 로그인 화면 정상
- [ ] `sudo systemctl status frms` → active (running)
- [ ] `sudo systemctl is-enabled frms` → enabled (재부팅 시 자동 시작)
- [ ] `sudo reboot` 후 서비스 자동 복구 확인
- [ ] SSH 인바운드가 내 IP로만 제한되어 있는지 보안 그룹 재확인
- [ ] Entra ID SSO 전환 완료 (또는 최소 IP 제한 적용)
- [ ] EBS "종료 시 삭제" 꺼짐 + 백업 크론 동작 확인 (SQLite 운영 시)
