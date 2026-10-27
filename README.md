# AutoCine AI Video Editor

Streamlit-ல் இயங்கும் எளிய வீடியோ எடிட்டர். வீடியோவை trim செய்யவும், social-media அளவுகளுக்கு மாற்றவும், preview செய்து MP4 ஆகப் பதிவிறக்கவும். Audio-ஐ மட்டும் M4A ஆகவும் எடுக்கலாம்.

இந்த MVP-யில் AI editing இன்னும் செயல்படுத்தப்படவில்லை. AI API key தேவையில்லை; எந்த AI சேவைக்கும் வீடியோ அனுப்பப்படாது.

## உள்ளூரில் இயக்குதல்

Python 3.10 அல்லது அதற்கு மேல் நிறுவப்பட்டிருக்க வேண்டும். Repository கோப்புகள் உள்ள Codespace terminal-ஐத் திறந்து:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Terminal காட்டும் இணைப்பைத் திறக்கவும். Streamlit Cloud-ல் upload அளவு பொதுவாக 200 MB-க்கு வரையறுக்கப்பட்டுள்ளது. ஆதரிக்கப்படும் கோப்பு வகைகள் MP4, MOV, M4V, MKV, WebM, AVI, MPEG, MPG, மற்றும் TS. கோப்பு உள்ளடக்கத்தின் codec-ஐப் பொறுத்து சில வீடியோக்கள் ஆதரிக்கப்படாமல் இருக்கலாம்.

## Streamlit Community Cloud-ல் வெளியிடுதல்

1. இந்த repository-யில் `app.py`, `requirements.txt`, மற்றும் `README.md`-ஐ GitHub-க்கு push செய்யவும்.
2. [share.streamlit.io](https://share.streamlit.io/) திறந்து GitHub மூலம் உள்நுழையவும்.
3. **Create app** தேர்ந்தெடுத்து இந்த repository, branch, மற்றும் main file path ஆக `app.py` தேர்வு செய்யவும்.
4. **Deploy** அழுத்தவும். Cloud, `requirements.txt`-ல் உள்ள packages-ஐ நிறுவி app-ஐத் தொடங்கும்.

## எடிட்டரில்

- வீடியோவைப் பதிவேற்றி filename, கால அளவு, resolution, மற்றும் preview பார்க்கலாம்.
- தொடக்கம்/முடிவு நேரத்தைத் தேர்ந்தெடுத்து Original, Vertical 9:16, Square 1:1, அல்லது Widescreen 16:9 preset-ஐப் பயன்படுத்தலாம்.
- **Process video** அழுத்தி MP4 உருவாக்கவும்; **Extract audio only** தேர்ந்தெடுத்தால் AAC M4A கிடைக்கும்.
- முடிவை preview செய்து download செய்யலாம். செயலாக்கம் தோல்வியுற்றால் திரையில் காரணம் காட்டப்படும்.

வீடியோ decode/encode-க்கு PyAV பயன்படுத்தப்படுகிறது. இது H.264 MP4 வெளியீட்டையும் AAC audio-வையும் உருவாக்குகிறது. எதிர்கால AI provider இணைப்பு விருப்பமானதாக இருக்கும்; தற்போது எந்த secret-யும் அமைக்க வேண்டியதில்லை.