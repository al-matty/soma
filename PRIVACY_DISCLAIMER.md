## ⚠️ Privacy & Data Sensitivity Disclaimer

Soma is local-first by design — your biomarker data, genetic variants, and health profiles are stored on your machine and never leave it at rest. However, if you use a cloud LLM provider (e.g., Anthropic's Claude API) for PDF extraction or health reasoning, your data is transmitted to that provider's servers.

Before using Soma with any cloud-based LLM, you should understand what you're sharing and why it matters.

### Genetic data is permanent

You can change a leaked password. You can't change your genome. Genetic variants — APOE status, BRCA mutations, MTHFR polymorphisms — are immutable facts about you for life. They are also not just about you: they reveal information about your parents, siblings, and children who never consented to sharing. If your genetic data leaks from any provider and gets linked to your identity, you can't un-ring that bell.

### Biomarker panels are more identifying than you think

Even "anonymized" biomarker data can be re-identified. A unique combination of 50+ lab values at specific dates, combined with age and sex, is effectively a fingerprint. If that data were ever correlated with other datasets, anonymization alone would not protect you.

### Insurance and discrimination risk

Depending on your jurisdiction, genetic and biomarker data may not be fully protected from use by insurers (life, disability, long-term care) or employers. Laws like GINA (US) and Gendiagnostikgesetz (Germany) offer partial protection, but coverage varies and enforcement is imperfect.

### LLM provider policies can change

API data retention policies, training data exclusions, and privacy commitments are only as durable as the company behind them. Providers can update terms, get acquired, or experience breaches. You are trusting that the provider's security posture and legal commitments hold for the lifetime relevance of your data — which, for genetic information, is forever.

### What you can do

- **Use `--method manual` for sensitive documents.** Extract data via local interaction and paste structured output into the pipeline. The raw PDF never leaves your machine.
- **Be selective about what goes to the API.** Routine blood panels have lower sensitivity and time-limited relevance compared to genetic reports. Consider reserving cloud LLM usage for non-genetic data.
- **Run a local model for reasoning over your full profile.** Use the cloud API for extraction where model quality matters most, and a local model for longitudinal analysis and health reasoning where your complete profile (including genetics) is in context.
- **Watch for confidential computing and on-device models.** The industry is moving toward trusted execution environments and capable local models. Soma's architecture is designed to support a local-only workflow when model quality catches up.

### Soma's position

Soma does not send any data anywhere by default. Cloud LLM usage is always an explicit, user-initiated action. The project's long-term goal is a fully local pipeline — cloud APIs are a practical bridge, not the destination.

This is your data. Treat it accordingly.
