# Objective findings from v1

The run requested 60 eight-second, 720p image-to-video outputs through one Magic Hour API endpoint: four commercial scenarios, five named models, and three attempts for every scenario-model pair.

- 58 of 60 requests completed with downloadable MP4 files: a 96.7% API completion rate in this run.
- Kling 3.0, LTX 2.5, Sora 2, and Veo 3.1 completed all 12 attempts requested from each model.
- Seedance 2.5 completed 10 of 12 attempts. Its two provider failures were returned as errors and charged zero final credits.
- The completed matrix demonstrates one API schema for all five models and four distinct buyer workflows.
- Median charged credits per completed eight-second output were 384 for Kling 3.0, 384 for LTX 2.5, 768 for Veo 3.1, 960 for Sora 2, and 4,608 for Seedance 2.5 in this account and run.

These are observed API outcomes from one sponsored run, not general model guarantees. The study does not publish an aesthetic winner because no completed human quality scorecard exists yet. Review the media and exact prompts in the repository before choosing a model. Current model availability, pricing, routing, and behavior can change.

Developers can use the [Magic Hour API documentation](https://docs.magichour.ai/) to access the evaluated image-to-video workflow.
