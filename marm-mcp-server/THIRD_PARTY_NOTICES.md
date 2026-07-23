# Third-Party Notices

MARM is licensed under the Apache License 2.0. This file records third-party
open-source components that MARM wraps, redistributes, or bakes into release
artifacts.

## spaCy English Pipeline (`en_core_web_sm`)

- **Project:** spaCy English small pipeline
- **Version:** 3.8.0
- **Source:** https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0
- **License:** MIT
- **Copyright:** Copyright 2021 ExplosionAI GmbH
- **Used by:** Bundled concept entity and relationship extraction.

The pipeline data is redistributed inside the MARM Python distribution so
concept extraction works after a normal install without a second model-download
step. The pipeline is loaded lazily only when concept extraction is used.

### MIT License Text

Copyright 2021 ExplosionAI GmbH

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## codebase-memory-mcp

- **Project:** codebase-memory-mcp
- **Version:** 0.8.1
- **Source:** https://github.com/DeusData/codebase-memory-mcp
- **License:** MIT
- **Copyright:** Copyright (c) 2025 DeusData
- **Used by:** MARM graph/index integration (`marm-graph`) and the unified
  `marm-mcp-server` Docker image.

MARM wraps the pinned `codebase-memory-mcp` engine and may bake its static
binary into Docker images so graph/index features work without a runtime
download. MARM does not own the upstream parser, indexer, graph engine,
vendored grammars, embedded model data, or binary release artifacts.

The upstream project also publishes its own third-party license summary for
vendored parser/runtime libraries, grammars, and embedded model data. When MARM
ships the upstream binary, those upstream notices remain applicable.

### MIT License Text

MIT License

Copyright (c) 2025 DeusData

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
