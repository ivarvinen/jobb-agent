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

GMAIL_USER = os.getenv('GMAIL_USER')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = genai.Client(api_key=GEMINI_API_KEY)

IVARS_CV = """
Senior UX/UI-designer och Art Director med över 10 års erfarenhet.
Söker roller som: Senior UX Designer, Product Designer, UI Designer eller Art Director.
Plats: Göteborg, Västra Götaland, eller 100% Remote. (Ignorera jobb som kräver on-site i andra städer).

Nyckelkompetenser:
- E2E UX, wireframes, prototyper (Figma), självserviceflöden.
- Designsystem & skalbarhet, WCAG-tillgänglighet (expertis inom offentlig sektor).
- Art Direction, varumärkesidentitet, konceptutveckling.
- Erfarenhet av Enterprise UX, SaaS (Mercell), Offentlig Sektor (VGR, Västtrafik).
- Agilt arbetssätt, Jira/Confluence, Stakeholder Management.
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
        # Logga in på Gmail
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        mail.select('inbox')

        # Hämta dagens datum minus 7 dagar
        date_since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        
        # Sök efter olästa mejl som inkommit de senaste 7 dagarna
        status, messages = mail.search(None, 'UNSEEN', 'SINCE', date_since)
        if status != 'OK' or not messages[0]:
            return jobs

        for num in messages[0].split():
            try:
                # Säkra upp ifall e-postens ID innehåller trasiga tecken
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
                
                # Vi är bara intresserade av LinkedIn och Indeed
                if "indeed.com" not in sender and "linkedin.com" not in sender:
                    continue
                    
                # Extrahera HTML-innehållet
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

                # Läs ut länkarna med BeautifulSoup
                soup = BeautifulSoup(body, 'html.parser')
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    text = a_tag.get_text(strip=True)
                    
                    # Filtrera ut jobbtitlarna
                    if text and 5 < len(text) < 100:
                        if any(word in text.lower() for word in ["unsubscribe", "sekretess", "privacy", "logga in", "jobb", "avregistrera"]):
                            continue
                        
                        if "indeed.com" in href or "linkedin.com" in href:
                            jobs.append({
                                'headline': text,
                                'employer': {'name': 'Företag nämns i länken'},
                                'workplace_address': {'municipality': 'Se annons/Remote'},
                                'webpage_url': href,
                                'description': {'text': 'Detta jobb hittades i ett e-postutskick. Bedöm relevansen utifrån jobbtiteln ovan.'},
                                'source': 'E-post'
                            })
            except Exception as inner_e:
                print(f"Hoppar över ett felaktigt mejl: {inner_e}")
                continue # Koden fortsätter snällt till nästa mejl

        mail.close()
        mail.logout()
        
        # Rensa eventuella dubbletter av samma jobb-länk
        unique_jobs = {job['webpage_url']: job for job in jobs}.values()
        return list(unique_jobs)
        
    except Exception as e:
        print(f"Kunde inte ansluta till inkorgen: {e}")
        return jobs

def analyze_job_with_ai(job):
    ad_text = job.get('description', {}).get('text', '')
    job_title = job.get('headline', '')
    job_location = job.get('workplace_address', {}).get('municipality', 'Okänd ort')
    
    prompt = f"""
    Du är en karriärcoach för Ivar. Bedöm om följande jobb är relevant för honom.
    
    IVARS PROFIL:
    {IVARS_CV}
    
    JOBBANNONS:
    Titel: {job_title}
    Ort: {job_location}
    Beskrivning: {ad_text}
    
    UPPGIFT:
    1. Ge matchningen en poäng mellan 1-10 (där 10 är ett perfekt drömjobb).
    2. Motivera kort varför (max 2 meningar).
    3. Ta hänsyn till orten! Om det kräver on-site i städer utanför Göteborg/Västra Götaland, ge poäng 1. (Om orten är "Se annons", dra inte av poäng).
    4. Observera: Vissa jobb saknar lång beskrivning eftersom de hämtats via mailutskick. Bedöm i så fall enbart utifrån titeln!
    
    Svara EXAKT med detta JSON-schema:
    {{"score": siffra, "motivation": "din motivering"}}
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
        print(f"Fel vid AI-analys: {e}")
        return {"score": 0, "motivation": "Kunde inte analyseras på grund av fel."}

def send_email(matched_jobs):
    if not matched_jobs:
        print("Inga relevanta jobb hittades idag.")
        return

    msg = EmailMessage()
    msg['Subject'] = f'🎯 {len(matched_jobs)} nya jobbmatchningar för Ivar!'
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER

    content = "God morgon Ivar!\n\nHär är dagens mest relevanta jobb, analyserade av din AI-agent:\n\n"
    for job in matched_jobs:
        content += f"💼 {job['title']} ({job.get('source', 'Platsbanken')})\n"
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
    
    print("Hämtar annonser från inkorgen (Indeed/LinkedIn)...")
    email_jobs = get_jobs_from_email()
    
    all_jobs = platsbanken_jobs + email_jobs
    print(f"Totalt hittades {len(all_jobs)} jobb att analysera. Startar AI...")
    
    matched_jobs = []
    
    for index, job in enumerate(all_jobs):
        print(f"Analyserar jobb {index + 1} av {len(all_jobs)}...")
        analysis = analyze_job_with_ai(job)
        score = analysis.get('score', 0)
        
        if score >= 7:
            matched_jobs.append({
                'title': job.get('headline', 'Okänd titel'),
                'company': job.get('employer', {}).get('name', 'Okänt företag'),
                'location': job.get('workplace_address', {}).get('municipality', 'Okänd ort'),
                'url': job.get('webpage_url', 'Ingen länk'),
                'source': job.get('source', 'Platsbanken'),
                'score': score,
                'motivation': analysis.get('motivation', '')
            })
            
        time.sleep(5)
        
    send_email(matched_jobs)

if __name__ == "__main__":
    main()
