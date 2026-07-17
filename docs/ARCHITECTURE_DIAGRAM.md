# docapture — Data-Flow Architecture Diagram

Component/data-flow view of the pipeline: how a document moves through the
system. For the class-level view (modules, methods, per-phase namespaces)
see `UML_DIAGRAM.md`. Same convention: solid = built, grey dashed = planned
(Phase 4, not started). Snapshot, not auto-synced — regenerate by hand when
the pipeline changes.

```mermaid
flowchart TD
    Upload[User uploads file\nvia Desk Attach] --> CD1[(Captured Document\nstatus: Uploaded)]
    CD1 -->|after_insert hook| EnqueueOCR[enqueue_ocr]

    subgraph OCR["OCR Layer — Phase 2, built"]
        EnqueueOCR -->|RQ queue: long| RunOCR[run_ocr]
        RunOCR --> PyMuPDF[PyMuPDF\nnative PDF text layer]
        RunOCR --> Preprocess[OpenCV preprocess\ndeskew / denoise / CLAHE]
        Preprocess --> Paddle[PaddleOCR PP-OCRv6\nprimary engine]
        Paddle -.on exception.-> Tesseract[Tesseract\nfallback engine]
    end

    RunOCR --> CD2[(Captured Document\nraw_ocr_json, status: OCR Done)]
    CD2 -->|chained enqueue| EnqueueMapper[run_mapper]

    subgraph Mapper["Mapper / LLM Layer — Phase 3, awaiting review"]
        EnqueueMapper -->|RQ queue: long| Classifier[classifier.classify\nkeyword heuristic + LLM fallback]
        Classifier --> PEMapper[payment_entry_mapper]
        Classifier --> JEMapper[journal_entry_mapper]
        PEMapper --> LLM[LLMParser\nOpenAI gpt-4.1 default\nor Claude opus-4.8]
        JEMapper --> LLM
        LLM -.traced.-> LangSmith[LangSmith tracing]
        PEMapper --> AliasResolver[alias_resolver]
        JEMapper --> AliasResolver
        AliasResolver <--> CapAlias[(Capture Alias\nlearned entity mappings)]
    end

    PEMapper --> CD3[(Captured Document\nextracted_json, confidence\nstatus: In Review)]
    JEMapper --> CD3

    subgraph Phase4["Review + Draft Creation — Phase 4, not started"]
        CD3 -.-> ReviewQueue[Review Queue]
        ReviewQueue -.-> Router[Router]
        Router -.-> PECreator[payment_entry_creator]
        Router -.-> JECreator[journal_entry_creator]
        PECreator -.-> PE[ERPNext Payment Entry\ndocstatus=0 draft]
        JECreator -.-> JE[ERPNext Journal Entry\ndocstatus=0 draft]
    end

    classDef planned fill:#f5f5f5,stroke:#9e9e9e,stroke-dasharray: 5 5,color:#757575
    class ReviewQueue,Router,PECreator,JECreator,PE,JE planned
```
