# AI-Powered Document Ingestion & Classification Pipeline

This project is an AI-powered, multi-agent system (MAS) designed to automate the entire lifecycle of document processing for enterprises. It automatically ingests, extracts, classifies, and routes unstructured documents at scale, providing full visibility into the process through a real-time web dashboard.

---

## Core Features

* **Multi-Agent Architecture:** Built on a robust, event-driven framework with four independent agents collaborating via a central message bus (RabbitMQ).
* **Multiple Ingestion Channels:** Supports document ingestion via a drag-and-drop Web API, automated File-share monitoring, and a dynamic Mailbox Connector for email attachments.
* **AI-Powered Intelligence:** Uses Tesseract for OCR and Google Gemini for cleaning text, extracting structured entities, and performing zero-shot classification.
* **Real-Time Operator Dashboard:** A modern React frontend provides live visibility with a WebSocket-powered, auto-updating table and an interactive workflow progress bar.
* **Manual Overrides:** The UI includes functional "Re-classify" and "Re-extract" buttons, allowing for human intervention.
* **Automated Routing:** Routes documents to real-world services like Google Sheets for logging and Slack for alerts.

---

## Technology Stack

* **Backend:** Python, FastAPI, Pika
* **Frontend:** React (Vite), Tailwind CSS, Framer Motion
* **AI / ML:** Google Gemini API, Tesseract OCR
* **Database:** SQLite
* **Message Bus:** RabbitMQ (Docker)
* **External Integrations:** Google Sheets API, Slack Webhooks, IMAP

---

## Getting Started on Windows

Follow these steps to set up and run the project on a Windows machine.

### 1. Prerequisites

Ensure you have the following software installed and configured in your system's PATH:
* **Python 3.10+**
* **Node.js & npm**
* **Docker Desktop** (must be running)
* **Tesseract OCR Engine**
* **Poppler** (for PDF processing)

### 2. Project Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd <project-folder>
    ```

2.  **Create and activate the Python virtual environment:**
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Install frontend dependencies:**
    ```bash
    cd web_ui\frontend
    npm install
    cd ..\..
    ```

### 3. Configuration & Secrets Setup

This project requires several external API keys and credentials. Follow the steps below to generate them, then create a file named `.env` in the root of the project and add your secrets to it.

#### **A. Google Gemini API Key**
This key is used by the Extractor and Classifier agents for AI-powered analysis.

1.  Go to the **Google Cloud Console** and create a new project.
2.  In the search bar, find and enable the **"Vertex AI API"**.
3.  Navigate to **APIs & Services > Credentials**.
4.  Click **+ Create Credentials** and select **API key**.
5.  Copy the generated key and add it to your `.env` file:
    ```env
    GOOGLE_API_KEY="your-google-api-key"
    ```

#### **B. Google Sheets API Credentials (JSON Key File)**
This is used by the Router agent to log processed documents.

1.  In the same Google Cloud project, find and enable the **"Google Sheets API"**.
2.  Go to **APIs & Services > Credentials**.
3.  Click **+ Create Credentials** and select **Service account**.
4.  Give the service account a name (e.g., `sheets-writer`) and grant it the **"Editor"** role.
5.  After the account is created, go to its **"Keys"** tab, click **"Add Key" > "Create new key"**, select **JSON**, and create it. A JSON key file will be downloaded.
6.  Save this file in the root of your project directory (e.g., `my-sheets-key.json`).
7.  Open your target Google Sheet, click **"Share"**, and share it with the service account's email address (found in the JSON file).
8.  Add the path to this file in your `.env`:
    ```env
    GOOGLE_SHEET_ID="your_google_sheet_id"
    GOOGLE_APPLICATION_CREDENTIALS="C:\\path\\to\\your\\credentials.json"
    ```

#### **C. Slack Incoming Webhook URL**
This is used by the Router agent to send alerts.

1.  Go to [api.slack.com/apps](https://api.slack.com/apps) and click **"Create New App"** (From scratch).
2.  Name it `Doc Processor Bot` and select your workspace.
3.  Go to **"Incoming Webhooks"** and activate them.
4.  Click **"Add New Webhook to Workspace"**, choose a channel, and click **"Allow"**.
5.  Copy the generated Webhook URL and add it to your `.env` file:
    ```env
    SLACK_WEBHOOK_URL="your_slack_webhook_url"
    ```

#### **D. Gmail App Password**
This is used by the "Connect Mailbox" feature.

1.  Go to your Google Account settings and ensure **2-Step Verification** is enabled.
2.  Navigate to the **"App passwords"** section.
3.  Under "Select app," choose **"Mail"**. Under "Select device," choose **"Other (Custom name)"**.
4.  Name it `Doc Processor Agent` and click **"Generate"**.
5.  Copy the 16-digit password. Users will enter this password in the UI when connecting their mailbox.

### 4. How to Run (using VS Code Tasks)

1.  **Open the project** in Visual Studio Code.
2.  Ensure your `.env` file is complete.
3.  Open the Command Palette (**`Ctrl+Shift+P`**), type **`Tasks: Run Task`**, and select **`Start All Services`**.

This will automatically start all backend agents and the frontend server. The main dashboard will be available at **`http://localhost:5173`**.

---

## How to Use

1.  **Upload a Document:** Drag and drop a file onto the upload panel.
2.  **Connect a Mailbox:** Click the "Connect New Mailbox" button and enter an email address and a generated App Password.
3.  **Watch in Real-Time:** Observe documents appear on the dashboard and their statuses update instantly.
4.  **Check the Output:** See the final record appear in your Google Sheet or receive an alert in your Slack channel.
