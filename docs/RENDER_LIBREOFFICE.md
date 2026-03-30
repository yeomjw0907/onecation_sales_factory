# Render LibreOffice Notes

`proposal.md -> docx -> pdf` 파이프라인은 서버에 LibreOffice CLI가 있어야 동작한다.

## 권장 방식

Render에서는 OS 패키지가 필요하므로 Docker 기반 배포를 권장한다.

필수 구성:

- LibreOffice (`soffice`)
- CJK 폰트 (`fonts-noto-cjk` 권장)
- 환경변수 `SALES_FACTORY_REQUIRE_PDF=1`
- 필요시 환경변수 `LIBREOFFICE_BIN=/usr/bin/soffice`

## 동작 방식

- `generate_pdf_playwright.py`가 먼저 고객용 `docx`를 생성한다.
- `soffice --headless --convert-to pdf`로 같은 문서를 PDF로 변환한다.
- `SALES_FACTORY_REQUIRE_PDF=1` 이면 PDF 변환 실패 시 배치를 실패로 처리한다.

## 확인 포인트

- Render 컨테이너 안에서 `soffice --version` 이 정상 동작하는지
- 일본어/한국어/영어 제안서가 모두 깨지지 않는지
- `output/` 폴더에 `.docx` 와 `.pdf` 가 함께 생성되는지
