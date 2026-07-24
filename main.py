import os
import requests
import json
import smtplib
import imaplib
import email
from email.header import decode_header
from email.message import EmailMessage
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup

from google import genai
from google.genai import types

GMAIL_USER = os.getenv('GMAIL_USER', '').replace('\xa0', '').replace(' ', '')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD', '').replace('\xa0', '').replace(' ', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SCRAPER_API_KEY = os.getenv('SCRAPER_API_KEY')

client = genai.Client(api_key=GEMINI_API_KEY)

IVARS_CV = """
Senior UX/UI-designer och Art Director med över 10 års erfarenhet.
Plats: Göteborg, Västra Götaland, eller 100% Remote. (Ignorera jobb som kräver on-site i andra städer).

# Vad jag söker i min nästa roll

## 1. Målbild & Roll
Jag letar efter en roll där jag får kombinera min tunga strategiska UX-grund med min passion för Art Direction, visuell identitet och varumärkesbyggande. Jag trivs bäst i hybridroller (exempelvis Lead Designer, Senior UX/UI Designer med AD-ansvar, eller Product Designer) där jag får ta ett helhetsgrepp om den digitala upplevelsen – från första koncept och varumärkesstrategi till pixelperfekt UI.

## 2. Arbetsmiljö & Kultur
Efter att ha navigerat i storskaliga, trögrörliga och politiskt styrda organisationer (främst offentlig sektor), söker jag mig nu till en mer snabbrörlig, kreativ och dynamisk miljö. Jag letar efter:
* En byrå, ett produktbolag eller en inhouse-avdelning med korta beslutsvägar och ett genuint designfokus.
* Ett arbetsklimat där design har ett strategiskt mandat och inte bara är en kravdriven funktionell leverans.
* Ett team som präglas av tätt och prestige-löst samarbete mellan design, tech och affär, snarare än arbete i silos.

## 3. Typ av projekt
* Kommersiella och varumärkesbyggande digitala tjänster, e-handel eller innovativa produkter.
* Projekt där det finns ett stort utrymme för "visuell verkshöjd" och kreativitet, i kontrast till ren systemförvaltning.
* Uppdrag där jag får använda min erfarenhet för att omvandla komplexa affärsbehov till eleganta, konverterande och användarvänliga gränssnitt som stärker varumärket.

## 4. Vad jag vill bidra med
Jag vill vara den trygga bryggan mellan det kreativa (Brand/AD) och det strukturella (UX/Tech). Med min breda bakgrund kan jag kliva in och höja den visuella kvaliteten, samtidigt som jag vet exakt hur man bygger skalbara designsystem, navigerar tillgänglighetskrav och kommunicerar sömlöst med utvecklingsteam för att säkerställa att visionen faktiskt blir verklighet.
"""

def get_recent_jobs_platsbanken():
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
    url = "https://jobsearch.api.jobtechdev.se/search"
    params = {
        'q': '"UX" OR "UI" OR "Art Director" OR "Product Designer"',
        'published-after': yesterday,
        'limit': 50
    }
    headers = {'accept': 'application/json'}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json().get('hits', [])
    return []

def get_jobs_from_email():
    jobs = []
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        mail.select('inbox')

        date_since = (datetime.now() - timedelta(days=30)).strftime("%d-%b-%Y")
        status, messages = mail.search(None, 'SINCE', date_since)
        
        if status != 'OK' or not messages[0]:
            return jobs

        for num in messages[0].split():
            try:
                clean_num = num.decode('ascii', errors='ignore')
                status, data = mail.fetch(clean_num, '(RFC822)')
                if status != 'OK':
                    continue
                
                raw_email = None
                for response_part in data:
                    if isinstance(response_part, tuple):
                        raw_email = response_part[1]
                        
                if not raw_email:
                    continue
                    
                msg = email.message_from_bytes(raw_email)
                sender = str(msg.get("From", "")).lower()
                
                if "indeed.com" not in sender and "linkedin.com" not in sender:
                    continue
                    
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            body_bytes = part.get_payload(decode=True)
                            if body_bytes:
                                body = body_bytes.decode('utf-8', errors='ignore')
                            break
                else:
                    if msg.get_content_type() == "text/html":
                        body_bytes = msg.get_payload(decode=True)
                        if body_bytes:
                            body = body_bytes.decode('utf-8', errors='ignore')

                if not body:
                    continue

                soup = BeautifulSoup(body, 'html.parser')
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    text = a_tag.get_text(strip=True)
                    
                    if text and 5 < len(text) < 100:
                        if any(word in text.lower() for word in ["unsubscribe", "sekretess", "privacy", "logga in", "jobb", "avregistrera"]):
                            continue
                        
                        if "indeed.com" in href or "linkedin.com" in href:
                            jobs.append({
                                'headline': text,
                                'employer': {'name': 'Okänt företag'},
                                'workplace_address': {'municipality': 'Se annons/Remote'},
                                'webpage_url': href,
                                'description': {'text': 'Detta jobb hittades i ett e-postutskick. Bedöm relevansen utifrån jobbtiteln ovan.'},
                                'source': 'E-post'
                            })
            except Exception as inner_e:
                continue

        mail.close()
        mail.logout()
        
        unique_jobs = {}
        for job in jobs:
            title_key = job['headline'].strip().lower()
            if title_key not in unique_jobs:
                unique_jobs[title_key] = job
                
        return list(unique_jobs.values())
        
    except Exception as e:
        print(f"Kunde inte ansluta till inkorgen: {e}")
        return jobs

def get_full_ad_text(url):
    if not SCRAPER_API_KEY:
        print("Scraper API-nyckel saknas. Hoppar över extrahering.")
        return None
    try:
        # Vi skickar vår URL via ScraperAPI för att lura Cloudflare
        payload = {'api_key': SCRAPER_API_KEY, 'url': url}
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=30)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Extraherar all text men rensar bort onödig kod
            text = soup.get_text(separator=' ', strip=True)
            return text[:4000] # Skickar med max 4000 tecken för att spara token-utrymme
    except Exception as e:
        print(f"Ett fel uppstod vid skrapning med ScraperAPI: {e}")
        pass
    return None

def analyze_job_with_ai(job):
    ad_text = job.get('description', {}).get('text', '')
    job_title = job.get('headline', '')
    job_location = job.get('workplace_address', {}).get('municipality', 'Okänd ort')
    
    prompt = f"""
    Du är en karriärcoach för Ivar. Bedöm om följande jobb är relevant för honom.
    
    IVARS PROFIL & PREFERENSER:
    {IVARS_CV}
    
    JOBBANNONS:
    Titel: {job_title}
    Ort: {job_location} (Viktigt: Om orten är "Hämtad via länk", leta efter staden i annonstexten nedan!)
    Beskrivning: {ad_text}
    
    UPPGIFT:
    1. Ge matchningen en poäng mellan 1-10 (där 10 är ett perfekt drömjobb). Väg in kultur, byrå/inhouse och utrymme för kreativitet.
    2. Motivera kort varför (max 2 meningar).
    3. Ta hänsyn till orten! Om det kräver on-site i städer utanför Göteborg/Västra Götaland, ge poäng 1.
    4. Leta efter arbetsgivarens/företagets namn i annonsen och spara det.
    
    Svara EXAKT med detta JSON-schema:
    {{"score": siffra, "company": "Företagsnamnet eller 'Okänt'", "location": "Staden eller Remote", "motivation": "din motivering"}}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite', 
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        return json.loads(response.text)
    except Exception as e:
        return {"score": 0, "company": "Okänt", "location": "Okänd", "motivation": "Kunde inte analyseras."}

def send_email(matched_jobs):
    if not matched_jobs:
        print("Inga relevanta jobb hittades idag.")
        return

    msg = EmailMessage()
    msg['Subject'] = f'🎯 {len(matched_jobs)} nya jobbmatchningar för Ivar!'
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER

    content = "God morgon Ivar!\n\nHär är de mest relevanta jobben, analyserade utifrån dina nya profilkrav:\n\n"
    for job in matched_jobs:
        content += f"💼 {job['title']} ({job.get('source', 'Platsbanken')})\n"
        content += f"🏢 Företag: {job['company']}\n"
        content += f"📍 {job['location']}\n"
        content += f"⭐ Matchning: {job['score']}/10\n"
        content += f"🤖 AI:ns motivering: {job['motivation']}\n"
        content += f"🔗 Länk: {job['url']}\n"
        content += "-" * 40 + "\n\n"
        
    content += "Lycka till med sökandet!\n/Din AI-agent"
    msg.set_content(content)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASSWORD)
        smtp.send_message(msg)
    print("Mejl skickat!")

def main():
    print("Hämtar annonser från Platsbanken...")
    platsbanken_jobs = get_recent_jobs_platsbanken()
    
    print("Hämtar annonser från inkorgen (Indeed/LinkedIn senaste 30 dagarna)...")
    email_jobs = get_jobs_from_email()
    
    all_jobs = platsbanken_jobs + email_jobs
    print(f"Totalt hittades {len(all_jobs)} unika jobb att analysera. Startar AI...")
    
    matched_jobs = []
    
    for index, job in enumerate(all_jobs):
        print(f"Analyserar jobb {index + 1} av {len(all_jobs)}...")
        
        if job.get('source') == 'E-post':
            scraped_text = get_full_ad_text(job['webpage_url'])
            if scraped_text:
                job['description']['text'] = scraped_text
                job['workplace_address']['municipality'] = 'Hämtad via länk'

        analysis = analyze_job_with_ai(job)
        score = analysis.get('score', 0)
        
        if score >= 7:
            matched_jobs.append({
                'title': job.get('headline', 'Okänd titel'),
                'company': analysis.get('company', job.get('employer', {}).get('name', 'Okänt företag')),
                'location': analysis.get('location', job.get('workplace_address', {}).get('municipality')),
                'url': job.get('webpage_url', 'Ingen länk'),
                'source': job.get('source', 'Platsbanken'),
                'score': score,
                'motivation': analysis.get('motivation', '')
            })
            
        time.sleep(5)
        
    send_email(matched_jobs)

if __name__ == "__main__":
    main()
