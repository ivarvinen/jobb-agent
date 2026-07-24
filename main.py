import os
import requests
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
import time  # <-- NYTT: Bibliotek för att kunna pausa koden

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

def get_recent_jobs():
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

def analyze_job_with_ai(job):
    ad_text = job.get('description', {}).get('text', '')
    job_title = job.get('headline', '')
    job_location = job.get('workplace_address', {}).get('municipality', 'Okänd ort')
    
    prompt = f"""
    Du är en karriärcoach för Ivar. Bedöm om följande jobbannons är relevant för honom.
    
    IVARS PROFIL:
    {IVARS_CV}
    
    JOBBANNONS:
    Titel: {job_title}
    Ort: {job_location}
    Beskrivning: {ad_text}
    
    UPPGIFT:
    1. Ge matchningen en poäng mellan 1-10 (där 10 är ett perfekt drömjobb).
    2. Motivera kort varför (max 2 meningar).
    3. Ta hänsyn till orten! Om det kräver on-site i städer utanför Göteborg/Västra Götaland (och inte är remote), ge poäng 1.
    
    Svara EXAKT med detta JSON-schema:
    {{"score": siffra, "motivation": "din motivering"}}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Fel vid analys: {e}")
        return {"score": 0, "motivation": "Kunde inte analyseras."}

def send_email(matched_jobs):
    if not matched_jobs:
        print("Inga relevanta jobb hittades idag.")
        return

    msg = EmailMessage()
    msg['Subject'] = f'🎯 {len(matched_jobs)} nya jobbmatchningar för Ivar!'
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER

    content = "God morgon Ivar!\n\nHär är dagens mest relevanta jobbannonser från Platsbanken, analyserade av din AI-agent:\n\n"
    for job in matched_jobs:
        content += f"💼 {job['title']} hos {job['company']}\n"
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
    print("Söker efter nya jobb...")
    jobs = get_recent_jobs()
    print(f"Hittade {len(jobs)} nya annonser. Analyserar med Gemini...")
    
    matched_jobs = []
    
    # Loopar igenom alla jobb, ett i taget
    for index, job in enumerate(jobs):
        print(f"Analyserar jobb {index + 1} av {len(jobs)}...")
        analysis = analyze_job_with_ai(job)
        score = analysis.get('score', 0)
        
        if score >= 7:
            matched_jobs.append({
                'title': job.get('headline', 'Okänd titel'),
                'company': job.get('employer', {}).get('name', 'Okänt företag'),
                'location': job.get('workplace_address', {}).get('municipality', 'Okänd ort'),
                'url': job.get('webpage_url', 'Ingen länk'),
                'score': score,
                'motivation': analysis.get('motivation', '')
            })
            
        # NYTT: Pausar i 5 sekunder innan nästa varv för att undvika "Rate Limit"
        time.sleep(5)
        
    send_email(matched_jobs)

if __name__ == "__main__":
    main()
