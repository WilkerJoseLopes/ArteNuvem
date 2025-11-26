import cloudconvert
import os

API_KEY = "AQUI_A_TUA_API_KEY"
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
