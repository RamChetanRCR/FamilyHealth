# FamilyHealth

## 1. Purpose

FamilyHealth is a private family health-record application.

It allows family members to:
- Upload prescriptions and health documents/images.
- Associate documents with a specific family member.
- Extract text from uploaded documents using OCR.
- Store prescription details and medicines.
- Maintain medicine inventory separately.
- Retrieve a family member's historical prescriptions and health records.
- Eventually provide a chatbot for searching and explaining stored records.

The system must keep each family member's data isolated.

---

## 2. Architecture

```text
Family UI
   ↓
FastAPI Backend
   ↓
PostgreSQL
   +
Private Document Storage
   ↓
OCR / Document Processing
   ↓
Structured Health Data
   ↓
FamilyHealth Agent
   ↓
FamilyHealth MCP Server
   ↓
Controlled Health Data Retrieval
   ↓
LLM
   ↓
Response
   ↓
UI