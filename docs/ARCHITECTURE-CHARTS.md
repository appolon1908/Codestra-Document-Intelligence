# Codestra-Document-Intelligence — Architecture Charts

> Repository: `appolon1908/Codestra-Document-Intelligence`  
> Baseline branch: `main`  
> Repository-local visual architecture. Update these diagrams when implementation or authority changes.

## 1. System context
```mermaid
flowchart LR
 A["Applications / operators"] --> B["Document Intelligence API"]
 B --> R["Codestra-Document-Intelligence<br/>Document intelligence orchestration service"]
 R --> S["job/document metadata"]
 R --> D["OCR workers / schemas / storage"]
```

## 2. Internal component architecture
```mermaid
flowchart TB
 I["Entrypoint / UI / API / CLI"] --> P["Identity, policy, validation"]
 P --> C["Core domain / orchestration"]
 C --> S["State / configuration / persistence"]
 C --> A["Adapters / integrations"]
 A --> X["Approved dependencies"]
 C --> O["Metrics, logs, traces, audit"]
```

## 3. Critical flow
```mermaid
sequenceDiagram
 participant U as Caller
 participant B as Codestra-Document-Intelligence
 participant P as Policy
 participant C as Core
 participant S as State
 participant X as Dependency
 U->>B: Request / event / action
 B->>P: Authenticate + validate
 P-->>B: Decision
 B->>C: Upload, classify, extract, validate and return structured result
 C->>S: Read / persist
 C->>X: Bounded integration
 X-->>C: Result / readback
 C-->>U: Normalized response
```

## 4. Deployment and promotion
```mermaid
flowchart LR
 F["Feature branch"] --> T["Tests / validation"]
 T --> PR["Pull request + review"]
 PR --> CI["CI green"]
 CI --> ST["Staging / isolated verification"]
 ST --> EX["Exact-SHA certification"]
 EX --> G{"Production approval?"}
 G -- No --> ST
 G -- Yes --> P["Production promotion"]
 P --> H["Health/readiness + rollback check"]
```

## 5. Observability and recovery
```mermaid
flowchart LR
 R["Codestra-Document-Intelligence"] --> M["Metrics"]
 R --> L["Logs / audit"]
 R --> T["Traces / correlation"]
 M --> O["Observability stack"]
 L --> O
 T --> O
 O --> A["Dashboards / alerts"]
 R --> B["Backup / config snapshot"]
 B --> RR["Restore / rollback rehearsal"]
```

## Ownership notes
- **Role:** Document intelligence orchestration service
- **Primary boundary:** Document Intelligence API
- **State/config:** job/document metadata
- **Dependencies/consumers:** OCR workers / schemas / storage
- Cross-repository effects must use reviewed contracts; production effects remain separately gated.
