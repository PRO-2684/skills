# Conference Paper Search

Application: `ai-conferences/conference-paper-search`  
Purpose: Search accepted ML conference papers.

- API schema: `GET https://ai-conferences-conference-paper-search.hf.space/gradio_api/info`
- Search endpoint: `POST https://ai-conferences-conference-paper-search.hf.space/gradio_api/call/v2/search`
- Poll result: `GET https://ai-conferences-conference-paper-search.hf.space/gradio_api/call/search/{event_id}`
- File inputs: `POST https://ai-conferences-conference-paper-search.hf.space/gradio_api/upload -F "files=@file.ext"` then pass file payload as `{"path": "<returned-path>", "meta": {"_type": "gradio.FileData"}, "orig_name": "file.ext"}`
- Auth: `Bearer $HF_TOKEN` (https://huggingface.co/settings/tokens)

### `/search` input contract

- `query` (string, default: `""`)
- `mode` (string, default: `"semantic"`, supports `semantic` and `keyword`)
- `conferences` (null or array[string], default: `null`)
    - `3DV`
    - `AAAI`
    - `ACL`
    - `COLM`
    - `CVPR`
    - `ECCV`
    - `EMNLP`
    - `ICASSP`
    - `ICCV`
    - `ICLR`
    - `ICML`
    - `ICRA`
    - `Interspeech`
    - `MICCAI`
    - `NAACL`
    - `NeurIPS`
    - `SIGGRAPH`
    - `SIGGRAPHAsia`
    - `WACV`
- `year_min` (null or integer, default: `null`)
- `year_max` (null or integer, default: `null`)
- `types` (null or array[string], default: `null`)
    - `poster`
    - `spotlight`
    - `oral`
    - `notable-top-25%`
    - `notable-top-5%`
    - `talk`
- `sort` (string, default: `"relevance"`)
    - `relevance`
    - `newest`
    - `upvotes` (HF upvotes)
- `limit` (integer, default: `200`)
