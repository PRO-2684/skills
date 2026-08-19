# Conference Paper Search

Application: `ai-conferences/conference-paper-search`  
Purpose: Search accepted ML conference papers.

- API schema: `GET https://ai-conferences-conference-paper-search.hf.space/gradio_api/info`
- Search endpoint: `POST https://ai-conferences-conference-paper-search.hf.space/gradio_api/call/v2/search`
- Poll result: `GET https://ai-conferences-conference-paper-search.hf.space/gradio_api/call/search/{event_id}`
- File inputs: `POST https://ai-conferences-conference-paper-search.hf.space/gradio_api/upload -F "files=@file.ext"` then pass file payload as `{"path": "<returned-path>", "meta": {"_type": "gradio.FileData"}, "orig_name": "file.ext"}`
- Auth: `Bearer $HF_TOKEN` (https://huggingface.co/settings/tokens)

### `/search` input contract

- `query`: Search query.
    - Type: `string`
    - Default: (empty)
- `mode`: Search mode.
    - Type: `string`
    - Default: `semantic`
    - Accepted values: `semantic`, `keyword`
- `conferences`: Conference filters.
    - Type: `null` or `array[string]`
    - Default: `null` (search all available conferences)
    - Accepted values: `3DV`, `AAAI`, `ACL`, `COLM`, `CVPR`, `ECCV`, `EMNLP`, `ICASSP`, `ICCV`, `ICLR`, `ICML`, `ICRA`, `Interspeech`, `MICCAI`, `NAACL`, `NeurIPS`, `SIGGRAPH`, `SIGGRAPHAsia`, `WACV`
- `year_min`: Filter by earliest publication year.
    - Type: `null` or `integer`
    - Default: `null`
- `year_max`: Filter by latest publication year.
    - Type: `null` or `integer`
    - Default: `null`
- `types`: Filter by presentation type.
    - Type: `null` or `array[string]`
    - Default: `null` (search all available types)
    - Accepted values: `poster`, `spotlight`, `oral`, `notable-top-25%`, `notable-top-5%`, `talk`
- `sort`: Result ordering.
    - Type: `string`
    - Default: `relevance`
    - Accepted values: `relevance`, `newest`, `upvotes` (HF upvotes)
- `limit`: Maximum results to return.
    - Type: `integer`
    - Default: `200`
