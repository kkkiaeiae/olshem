# Онлайн орналастыру (demo сілтемесін алу)

Ұсыныс: **Hugging Face Spaces (Docker)** — тегін, 2 vCPU / 16 ГБ RAM (LibreOffice үшін жеткілікті), тұрақты сілтеме
`https://<аккаунт>-olshem.hf.space`. Render-дің тегін деңгейі (512 МБ RAM, 15 минуттан соң «ұйықтайды») LibreOffice үшін тар.

## A. Hugging Face Spaces (≈10 минут)

1. https://huggingface.co → тіркелу (немесе кіру).
2. **New → Space**: атауы `olshem`, SDK — **Docker** (Blank), Hardware — *CPU basic (free)*, Visibility — **Public**.
3. Space беті → **Settings → Variables and secrets → New secret**: `GEMINI_API_KEY` = сіздің кілтіңіз.
   (Кілт тек осында сақталады, кодқа түспейді.)
4. Кодты жүктеу — екі жолдың бірі:
   * **Браузер арқылы:** Space → *Files → Add file → Upload files* → репозиторийдегі барлық файл мен қалталарды сүйреп
     тастаңыз (`samples_private/`, `data/`, `.env` — **салмаңыз**).
   * **git арқылы:**
     ```bash
     git clone https://huggingface.co/spaces/<аккаунт>/olshem hf-olshem
     cp -r olshem/* olshem/.dockerignore olshem/.gitignore hf-olshem/   # samples_private жоқ екенін тексеріңіз
     cd hf-olshem && git add . && git commit -m "Өлшем" && git push
     ```
     (Құпиясөз орнына HF *Access Token* — Settings → Access Tokens → *Write*.)
5. Репозиторийдегі README.md басында Spaces-ке керек блок **бар** (өзгертудің қажеті жоқ):
   ```yaml
   ---
   title: Өлшем
   emoji: 📏
   colorFrom: blue
   colorTo: green
   sdk: docker
   app_port: 7860
   pinned: true
   ---
   ```
6. *Building* → *Running* болғанша күтіңіз (алғашқы құрастыру 5–8 минут, LibreOffice орнатылады).
7. Тексеру: `https://<аккаунт>-olshem.hf.space/api/health` → `"libreoffice": true`, модельдердің біреуі `"ok"`.
   `?refresh=true` — модельдерді қазір қайта тексеру.

**Ескерту:** тегін Space 48 сағат белсенділік болмаса ұйықтайды, ал қайта іске қосылғанда база тазарады (демо деректер
автоматты түрде қайта жүктеледі). Қорғау алдында сілтемені бір рет ашып, «оятып» қойыңыз.

## B. Render (балама)

1. Кодты GitHub-қа салыңыз (`.env`, `samples_private/` жоқ).
2. https://render.com → **New → Web Service** → репозиторий → Runtime: **Docker**.
3. Instance: кемінде *Starter* (512 МБ-тан көп RAM ұсынылады). Environment: `GEMINI_API_KEY`, `PORT=7860`.
4. Health check path: `/api/health`. Deploy.

## C. Қорғау күнгі тексеру тізімі

- [ ] `/api/health` — `libreoffice: true`, кемінде бір модель `ok`.
- [ ] Оқытушы → «Деректер базасы және SQL сұратымдар · Курстық жұмыс» ашылады, тізім расталған.
- [ ] Студент → «Үлгі жұмыспен көру» → есеп ~45 секундта шығады.
- [ ] ЖИ 503/429 берсе: Оқытушы бетінде **Демо режимін** қосыңыз (есепте ашық белгіленеді).
- [ ] Резерв: ноутбукта жергілікті нұсқа (`docker run -p 7860:7860 -e GEMINI_API_KEY=… olshem`).
