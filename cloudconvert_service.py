import cloudconvert
import os

API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiYjQ1MGU0ODg3NGE0NGNiNDk5N2Y4Yzk5YzM4YzBjYTZjZGUyODZlYjJmNzk1ODVmOWJkMDc0YTBjNjFmNDhmYjRkNjgxYWM4NjdiYTcxNDgiLCJpYXQiOjE3NjQxMTc2MDUuNTI0OTY2LCJuYmYiOjE3NjQxMTc2MDUuNTI0OTY3LCJleHAiOjQ5MTk3OTEyMDUuNTE4NzM0LCJzdWIiOiI3MzU3MjM3MCIsInNjb3BlcyI6WyJ1c2VyLnJlYWQiLCJ0YXNrLndyaXRlIiwidGFzay5yZWFkIl19.mllypo6UpQJgyo3a2g2dZ5V01CmkV1VFADKBWz1RqVPb3WC8K0RTG4QaOBUyM8YekT_xGvRFedwJu6BjGvuWTHXA1ua3dH0-euNR1ALsXQYk0dGRPrkP2uQTlAlxUwrR6GI0X_Ejuae0bkrN7pUbxy2-sxznCZATeaQl6fuV_JImfESj0ryqjoXIvtpcqmWlLYN4yXMjawZiOPbfMyfJJy-_pvLrvOxGrPtu1BNcjbfQzcAO1ZnfS8BOgMxnv0ztns7H4LD3kPaKDcdmqeJZpNV4qWR_Wux8imcanHmDAiXMNanF2nzPVx7TSkssrDiTfxTXPYaYuKICpTwDG_Pw1Mjn-KJKXHjCF1VZ4Vd7SwpZuf9hDDET6yBl4oEnHUjMDkfQDMBDHK7LiyXASq6y3AzHmUhw3cq2IBpg8hjh-ZODSX7RAl-Rl_4hja99Du7as4SLdkzRY0ovW6ZJH_gUqQEo6DC9NF-66qcjLWOEoz0Ql6x8nUeWlRgv62JjJUJiZk6Jdd67Yw7HS_Yqwg7PBjcbwtb_Owib94fHrdbv5QiLlOhNcCVPTcq-NZ_URgshxG3Ioh7lwiJeY7kVQuGz-ZO8WTkdQ4-3EdAADaeqyXfDfo_l5xw1CJ2OGDmpZmflIC7bUMmJJ4WPxiMNmZfdDVE_awqBXZK5qwE8Wv0DaKY"
cloudconvert.configure(api_key=API_KEY, sandbox=False)

def html_para_pdf(html_path, pdf_path):
    job = cloudconvert.Job.create(payload={
        "tasks": {
            "import-html": {
                "operation": "import/upload"
            },
            "convert-file": {
                "operation": "convert",
                "input": "import-html",
                "output_format": "pdf"
            },
            "export-file": {
                "operation": "export/url",
                "input": "convert-file"
            }
        }
    })

    upload_task = job["tasks"][0]
    upload_url = upload_task["result"]["form"]["url"]
    form_data = upload_task["result"]["form"]["parameters"]

    # Faz upload do ficheiro HTML
    with open(html_path, "rb") as f:
        cloudconvert.Task.upload(upload_task, f)

    # Fetch do PDF resultante
    exported = cloudconvert.Task.wait(job["tasks"][2]["id"])
    file_url = exported["result"]["files"][0]["url"]

    # Guardar PDF localmente
    import requests
    r = requests.get(file_url)
    with open(pdf_path, "wb") as f:
        f.write(r.content)

    return pdf_path
