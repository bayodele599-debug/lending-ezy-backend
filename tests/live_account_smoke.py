"""Full synthetic real-HTTP journey against PostgreSQL and Mailpit.

Requires development mode and loopback Mailpit. Never sends a real email or
creates personal data. Covers register -> verify -> account plans -> submission
-> admin conversation -> customer reply -> password reset.
"""
import json
import os
import re
import time
from uuid import uuid4
import httpx

API=os.getenv("LOCAL_API_URL","http://127.0.0.1:8000")
MAIL=os.getenv("MAILPIT_URL","http://127.0.0.1:8025")
ADMIN=os.getenv("ADMIN_API_TOKEN","")
if os.getenv("APP_ENV")!="development" or len(ADMIN)<32:
    raise SystemExit("Refusing to run outside the protected local integration environment")


def email_token(client, email, subject_fragment):
    """Read only synthetic test mail from the local inbox; never dump token to logs."""
    for _ in range(30):
        res=client.get(MAIL+"/api/v1/messages?limit=100")
        if res.status_code==200:
            items=res.json().get("messages",[])
            for item in items:
                if email.lower() in json.dumps(item).lower() and subject_fragment.lower() in json.dumps(item).lower():
                    detail=client.get(MAIL+"/api/v1/message/"+item["ID"])
                    assert detail.status_code==200,detail.text
                    raw=json.dumps(detail.json())
                    hit=re.search(r"token=([A-Za-z0-9_-]{32,256})",raw)
                    if hit:
                        return hit.group(1)
        time.sleep(.5)
    raise AssertionError("Expected synthetic email was not captured in Mailpit")


with httpx.Client(base_url=API,timeout=15) as client:
    email="account-%s@example.com" % uuid4().hex
    password="Safe integration passphrase 2026!"
    register=client.post("/api/v1/account/register",json={
        "full_name":"Synthetic Customer","email":email,"country":"GB",
        "password":password,"consent_to_terms":True})
    assert register.status_code==201,register.text
    bad=client.post("/api/v1/account/login",json={"email":email,"password":password})
    assert bad.status_code==403,bad.text
    token=email_token(client,email,"Verify")
    assert client.post("/api/v1/account/verify-email",json={"token":token}).status_code==200
    login=client.post("/api/v1/account/login",json={"email":email,"password":password})
    assert login.status_code==200,login.text
    bearer={"Authorization":"Bearer "+login.json()["token"]}
    assert client.get("/api/v1/account/me",headers=bearer).json()["email"]==email
    saved=client.post("/api/v1/account/plans",headers=bearer,json={
        "type":"business","purpose":"Working capital","country":"GB","currency":"GBP",
        "amount":"35000","months":36,"annual_rate":"9.50"})
    assert saved.status_code==201,saved.text
    pid=saved.json()["id"]
    assert any(x["id"]==pid for x in client.get("/api/v1/account/plans",headers=bearer).json()["plans"])
    request=client.post("/api/v1/financing-requests",headers=bearer,json={
        "client_token":str(uuid4()),"kind":"business","purpose":"Working capital",
        "country":"GB","currency":"GBP","amount":"35000.00","term_months":36,
        "assumed_annual_rate":"9.50","name":"Synthetic Customer","email":email,
        "business_name":"Synthetic Business Ltd","consent_to_contact":True,
        "confirms_estimate_only":True})
    assert request.status_code==201,request.text
    ref=request.json()["reference"]
    assert any(x["id"]==ref for x in client.get("/api/v1/account/requests",headers=bearer).json()["requests"])
    assert client.get("/api/v1/account/requests/"+ref+"/messages").status_code==401
    admin={"X-Admin-Key":ADMIN}
    review=client.patch("/api/v1/admin/financing-requests/"+ref,headers=admin,json={
        "status":"needs_information","expected_status":"submitted",
        "note":"Private internal test note. Not visible to the customer."})
    assert review.status_code==200,review.text
    sent=client.post("/api/v1/admin/financing-requests/"+ref+"/messages",headers=admin,
        json={"body":"Please provide the expected purchase date."})
    assert sent.status_code==201,sent.text
    thread=client.get("/api/v1/account/requests/"+ref+"/messages",headers=bearer)
    assert thread.status_code==200 and len(thread.json()["messages"])==1,thread.text
    assert "Private internal" not in thread.text
    reply=client.post("/api/v1/account/requests/"+ref+"/messages",headers=bearer,
        json={"body":"We expect to purchase equipment next quarter."})
    assert reply.status_code==201,reply.text
    assert len(client.get("/api/v1/admin/financing-requests/"+ref+"/messages",headers=admin).json()["messages"])==2
    assert client.post("/api/v1/account/password/request-reset",json={"email":email}).status_code==200
    reset=email_token(client,email,"Reset")
    changed=client.post("/api/v1/account/password/reset",json={
        "token":reset,"password":"A new very secure passphrase 2026!"})
    assert changed.status_code==200,changed.text
    assert client.get("/api/v1/account/me",headers=bearer).status_code==401
    print("PASS: PostgreSQL + Mailpit account verification, persistent plans, linked request, admin/customer thread, reset and session revocation.")
