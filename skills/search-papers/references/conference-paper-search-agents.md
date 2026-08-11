# Conference Paper Search Agent Instructions

> Adapted from [source](https://huggingface.co/spaces/ai-conferences/conference-paper-search/agents.md) at 2026-08-11.

To use this application (`ai-conferences/conference-paper-search`: Search AI conference papers with semantic or keyword queries):

- API schema: `GET https://ai-conferences-conference-paper-search.hf.space/gradio_api/info`
- Call endpoint: `POST https://ai-conferences-conference-paper-search.hf.space/gradio_api/call/v2/{endpoint} {"param_name": value, ...}`
- Poll result: `GET https://ai-conferences-conference-paper-search.hf.space/gradio_api/call/{endpoint}/{event_id}`
- File inputs: `POST https://ai-conferences-conference-paper-search.hf.space/gradio_api/upload -F "files=@file.ext"`, use as: `{"path": "<returned-path>", "meta": {"_type": "gradio.FileData"}, "orig_name": "file.ext"}`
- Auth: `Bearer $HF_TOKEN` (https://huggingface.co/settings/tokens)
