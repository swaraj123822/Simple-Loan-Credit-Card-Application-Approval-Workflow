# Configurable Workflow Decision Platform

[cite_start]A lightweight, configurable workflow decision engine built to handle real-world business workflows under ambiguity, changing requirements, and operational constraints[cite: 2]. [cite_start]This system processes incoming requests, evaluates rules dynamically, maintains state, records comprehensive audit trails, and handles external dependency failures gracefully[cite: 5].

[cite_start]Currently configured for a **Loan Application Approval Workflow**, the system is generic enough to support multiple business use cases via a simple JSON configuration[cite: 6].

## Core Capabilities
* [cite_start]**Dynamic Rules Engine:** Evaluates mandatory checks, thresholds, and multi-step conditional branching based on a `config.json` file[cite: 11]. [cite_start]No major code rewrites are required to change the workflow[cite: 29].
* [cite_start]**Idempotency & State Management:** Tracks request lifecycles and strictly enforces idempotency—duplicate requests return the exact cached state without triggering unintended side effects[cite: 13, 27].
* [cite_start]**Resilience & Failure Handling:** Simulates an external dependency (Credit Bureau API) with built-in retry mechanisms to handle transient failures[cite: 15, 26].
* [cite_start]**Strict Auditability:** Maintains a full database-backed audit log of every rule trace, system action, and decision explanation[cite: 14, 28].

##  Tech Stack
* **Language:** Python 3.9+
* [cite_start]**Framework:** FastAPI (REST API Interface) [cite: 21]
* **Validation:** Pydantic
* **Database:** SQLite (Zero-setup state and audit management)

##  Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd decision-platform
