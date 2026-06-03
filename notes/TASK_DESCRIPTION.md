# Task Description: Medior AI Engineer

## Project: Agentic RAG Chatbot Prototype Development

The task is to develop an **Agentic RAG (Retrieval-Augmented Generation)** based chatbot prototype in Python, using the **LangGraph framework**. The goal is a working, well-documented, and reproducible solution that demonstrates confident knowledge of designing agentic systems and integrating modular RAG subsystems.

---

## 1. Problem Definition and Data Source

### Problem Selection
Choose a real-world problem (domain/use case) for which the chatbot provides a solution.

### Justification
In the documentation, briefly justify your choice according to the following aspects:
- Why is the problem relevant?
- What user need does it fulfill?
- Why is the agentic RAG approach advantageous for it?

---

## 2. Architecture and Agentic Operation

### Agentic Workflow (LangGraph)
Create an agentic workflow using the LangGraph framework that contains **at least 5 nodes**. Your graph must include:
- Autonomous decision-making (e.g. conditional routing)
- Decomposition into subtasks and independent execution
- State management for storing intermediate results

### Tools
Integrate **at least 2 tools** into the workflow. In addition to the RAG functionality, there must be at least one tool that is not purely for retrieval purposes.

### RAG Subsystem
Create a dedicated, modular **RAG subgraph**, which is callable from the main workflow but **does not count toward the 3–5 nodes**.

### Data Source
Use a freely chosen text-based data source (e.g. PDF documents, public datasets, articles). The emphasis is on **quality processing** and **scalable data integration**, not on quantity.

---

## 3. Technical Implementation and UI

### Model Selection
**Do not use paid APIs.** Choose an open-source LLM suited to your local resources, and briefly justify your choice in the documentation (trade-offs). If this is not possible, the use of dummy LLMs is also acceptable.

### User Interface (UI)
Create a simplified prototype UI using **Streamlit**, which demonstrates:
- The main steps of the agent's operation
- The result of the RAG process

### Runtime Environment
Your solution must be containerized:
- Preparing a **Dockerfile** is mandatory
- Bonus: wrapping multi-component solutions (e.g. UI, API) together with a **docker-compose.yml**

---

## 4. Evaluation and Performance Analysis

### Functional Evaluation
Compile a **mini evaluation set of 10–20 questions** for your chosen problem, and evaluate your system's performance on either 1 node or the full agentic workflow.

### Performance Test (Load Scenario)
Present a simplified load test (**50–200 queries**). Summarize the results with:
- Basic latency metrics
- Identification of the system's main bottleneck
- 1–2 concrete optimization suggestions

---

## 5. Deliverables and Evaluation Criteria

### Deliverables
- The complete project **source code** in a Git repository
- **Dockerfile** (and optionally **docker-compose.yml**) for reproducibility
- A **README.md** documentation that includes:
  - Description of the problem and the objective
  - Overview of the system architecture and justification of design decisions
  - Summary of the functional evaluation and performance test results
  - Installation and running guide

### Evaluation Criteria
- Code quality and readability
- Reproducibility of the solution
- Relevance and justification of the problem selection
- Quality of the agentic architecture and LangGraph implementation
- Evaluation methodology and conclusions drawn
- Depth of performance analysis and bottleneck analysis
