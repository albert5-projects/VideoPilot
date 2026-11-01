# Provider documentation consulted

Checked 22 October 2026. Availability, terms and quotas can change.

- Codex authentication: https://learn.chatgpt.com/docs/auth
- Codex non-interactive execution: https://learn.chatgpt.com/docs/non-interactive-mode
- Codex CLI flags and schema output: https://learn.chatgpt.com/docs/cli/reference
- Codex model availability: https://learn.chatgpt.com/docs/models
- Codex subscription pricing: https://learn.chatgpt.com/docs/pricing
- Google AI plans and separate API billing: https://ai.google.dev/gemini-api/docs/google-ai-plans
- Gemini image generation: https://ai.google.dev/gemini-api/docs/image-generation
- Gemini generateContent endpoint: https://ai.google.dev/api/generate-content
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Kokoro ONNX code, voices and model setup: https://github.com/thewh1teagle/kokoro-onnx
- Kokoro example/model download locations: https://github.com/thewh1teagle/kokoro-onnx/blob/main/examples/save.py
- pyCapCut's version-specific validation illustrates why recent draft generators cannot establish old-version compatibility: https://github.com/GuanYixuan/pyCapCut/blob/main/english_readme.md

VideoPilot does not depend on pyCapCut. It uses your native plain project as a schema sample. This is still an experimental compatibility approach, not an official CapCut integration.

Third-party licensing: kokoro-onnx wrapper MIT; Kokoro model Apache 2.0 according to its upstream documentation. The espeak phonemizer and other dependencies have their own licenses. Models and dependency binaries are downloaded separately and are not bundled in this ZIP. Review relevant licenses before redistributing the app and its downloaded dependencies. Own the rights to any music, images or reference material you import; an AI-generated asset is not a guarantee of exclusive rights or platform monetization eligibility.

## Flow edition references — 23 October 2026

- Flow image mode, model choice, aspect ratio and output count: https://support.google.com/flow/answer/16729550?hl=en
- Flow usage/credits and changing limits: https://support.google.com/flow/answer/16526234?hl=en
- Temporary user-activated tab access: https://developer.chrome.com/docs/extensions/develop/concepts/activeTab
- Content scripts and isolated worlds: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts
- Browser-managed downloads and completion states: https://developer.chrome.com/docs/extensions/reference/api/downloads

The Flow edition uses browser UI, not the Gemini developer API. Earlier API references remain for the previous provider implementation. There is no verified official subscription automation API integrated here, and the current Google documentation does not justify a blanket unlimited-generation promise for every image model/account.
