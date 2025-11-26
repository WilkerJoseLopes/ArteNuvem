import os
import requests
import cloudconvert

API_KEY = os.getenv("CLOUDCONVERT_API_KEY")
if not API_KEY:
    raise RuntimeError("CLOUDCONVERT_API_KEY não definida nas variáveis do Render")

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

    upload_task = [t for t in job["tasks"] if t["name"] == "import-html"][0]

    with open(html_path, "rb") as f:
        cloudconvert.Task.upload(upload_task, f)

    job = cloudconvert.Job.wait(job["id"])
    export_task = [t for t in job["tasks"] if t["name"] == "export-file"][0]
    file_url = export_task["result"]["files"][0]["url"]

    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    r = requests.get(file_url)
    with open(pdf_path, "wb") as f:
        f.write(r.content)

    return pdf_path

