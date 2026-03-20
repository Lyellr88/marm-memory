 # Qwen-Code NLP-Based Tool Invocation - Technical Analysis (Part 1) 

   ## KEY FINDINGS

   ### 1. Tool Definition Pattern

   **File Structure:** `packages/core/src/tools/`

   Each tool consists of THREE components:
   1. **Tool Parameters Interface** - TypeScript interface defining inputs
   2. **Tool Invocation Class** - Executes the tool with given parameters
   3. **Tool Class** - Extends BaseDeclarativeTool, defines schema and builds invocations

   Example: ReadFileTool
   - Params: `ReadFileToolParams` (absolute_path, offset?, limit?)
   - Schema: JSON Schema defining parameter types and requirements
   - Invocation: `ReadFileToolInvocation` handles actual execution
   - Tool: `ReadFileTool` connects everything together

   ### 2. JSON Schema for Tool Parameters

   NOT TypeScript types, but actual JSON Schema objects:

   ```typescript
   parameterSchema: {
     type: 'object',
     properties: {
       absolute_path: {
         type: 'string',
         description: 'The absolute path to the file to read'
       },
       offset: {
         type: 'number',
         description: 'Optional: line number to start reading'
       },
       limit: {
         type: 'number',
         description: 'Optional: number of lines to read'
       }
     },
     required: ['absolute_path'],
     type: 'object'
   }
   ```

   This gets sent to LLM via Gemini/OpenAI API.

   ### 3. Tool Registration & Discovery

   **ToolRegistry** serves two purposes:
   1. **Built-in tools** - Registered programmatically
   2. **Dynamic tools** - Discovered from external commands or MCP servers

   Command discovery format:
   ```bash
   # Config specifies a tool discovery command
   config.toolDiscoveryCommand = "my-script discover-tools"

   # Script returns JSON array
   [
     {
       "name": "custom_tool",
       "description": "What it does",
       "parametersJsonSchema": { ... }
     }
   ]
   ```

   ### 4. Validation Architecture

   **Two layers:**
   1. **JSON Schema validation** - Automatic against parametersJsonSchema
   2. **Custom validation** - Override `validateToolParamValues()` for domain logic

   ```typescript
   // Auto-validated against schema
   validateToolParams() {
     return SchemaValidator.validate(schema, params);
   }

   // Custom validation layer
   validateToolParamValues(params: ReadFileToolParams): string | null {
     if (!path.isAbsolute(params.absolute_path)) {
       return 'File path must be absolute';
     }
     // ... more checks
   }
   ```

   ### 5. Tool Confirmation Workflow

   Three approval modes:
   1. **YOLO** - Auto-approve everything (dev only)
   2. **PLAN** - Only allow read-only operations
   3. **NORMAL** - Require approval for sensitive operations

   Sensitive operations determined by:
   - Tool kind (Edit, Delete, Move, Execute are mutators)
   - Custom logic via `shouldConfirmExecute()`

   ```typescript
   async shouldConfirmExecute(): Promise<ConfirmationDetails | false> {
     // Return false = auto-approve
     // Return ConfirmationDetails = ask user

     if (this.isSafeCommand()) return false;

     return {
       type: 'exec',
       title: 'Confirm Shell Command',
       command: this.params.command,
       onConfirm: async (outcome) => {
         // Handle user decision
       }
     };
   }
   ```

   ### 6. Tool Execution States

   FSM with 7 states:
   ```
   validating (parameter checking)
     ├─> scheduled (no confirmation needed)
     └─> awaiting_approval (confirmation needed)
          └─> executing (running)
               └─> success/error/cancelled (terminal)

   error (validation failed) - terminal
   ```

   ### 7. Format Conversion (Gemini ↔ OpenAI)

   **Problem:** Different LLM APIs use different tool call formats

   **Solution:** OpenAIContentConverter class handles bidirectional conversion

   OpenAI → Gemini:
   ```typescript
   convertOpenAIResponseToGemini(openaiResponse) {
     // Convert tool_calls array to functionCall parts
     // Convert arguments string to parsed args object
   }
   ```

   Gemini → OpenAI:
   ```typescript
   convertGeminiToolParametersToOpenAI(params) {
     // Normalize type names (INTEGER → integer)
     // Convert numeric constraints from strings to numbers
   }
   ```

   This abstraction allows MARM to work with any LLM backend.

   ### 8. Error Handling

   Structured error types (not just strings):

   ```typescript
   enum ToolErrorType {
     TOOL_NOT_REGISTERED,
     INVALID_TOOL_PARAMS,
     EXECUTION_FAILED,
     FILE_NOT_FOUND,
     PERMISSION_DENIED,
     UNHANDLED_EXCEPTION,
     // ... more
   }

   interface ToolResult {
     llmContent: any,           // Content for LLM history
     returnDisplay: string,     // User-facing display
     error?: {
       message: string,
       type: ToolErrorType      // Machine-readable error
     }
   }
   ```

   LLM can understand and respond meaningfully to structured errors.

   ### 9. Live Output Streaming

   Tools can emit updates during execution:

   ```typescript
   // In tool execute() method
   async execute(signal, updateOutput?) {
     // updateOutput callback for live updates
     for (const chunk of results) {
       updateOutput?.(chunk);  // Stream to UI immediately
     }
     return finalResult;
   }

   // In scheduler
   const liveOutputCallback = tool.canUpdateOutput
     ? (outputChunk) => {
         this.outputUpdateHandler?.(callId, outputChunk);
         // UI updates in real-time
       }
     : undefined;
   ```

   ### 10. Tool Registry Query APIs

   ```typescript
   // Get all tools
   getAllTools(): AnyDeclarativeTool[]
   getAllToolNames(): string[]

   // Get filtered
   getFunctionDeclarations(): FunctionDeclaration[]
   getFunctionDeclarationsFiltered(names: string[]): FunctionDeclaration[]

   // Lookup specific
   getTool(name: string): AnyDeclarativeTool | undefined

   // MCP-specific
   getToolsByServer(serverName: string): AnyDeclarativeTool[]
   ```

   ---

   ## FILE REFERENCE

   ### Core Tool Files
   - `tool-names.ts` - ToolNames constants
   - `tools.ts` - DeclarativeTool, ToolInvocation base classes
   - `tool-registry.ts` - ToolRegistry, tool discovery
   - `tool-error.ts` - ToolErrorType enum

   ### Scheduler & Execution
   - `coreToolScheduler.ts` - Main orchestrator (1200+ lines)
   - `nonInteractiveToolExecutor.ts` - Batch execution
   - `streamingToolCallParser.ts` - Parse streamed tool calls

   ### LLM Integration
   - `client.ts` - GeminiClient.setTools() entry point
   - `converter.ts` - Format conversion (Gemini ↔ OpenAI)
   - `openaiContentGenerator.ts` - OpenAI client

   ### Tool Examples
   - `read-file.ts` - ReadFileTool (simple)
   - `shell.ts` - ShellTool (complex with confirmation)
   - `edit.ts` - EditTool (diff-based file modification)
   - `write-file.ts` - WriteFileTool
   - `task.ts` - TaskTool (subagent execution)

   ---

   ## DESIGN PRINCIPLES

   1. **Separation of Concerns**
      - Tool definition ≠ Execution ≠ Scheduling
      - Each layer has single responsibility

   2. **Strong Typing**
      - Generic <TParams, TResult> prevents type mismatches
      - ToolInvocation type-safe result

   3. **No Silent Failures**
      - Validation errors before execution
      - User confirmation for sensitive ops
      - Detailed error messages with suggestions

   4. **Progressive Enhancement**
      - Basic tools just implement execute()
      - Advanced: custom validation, confirmation, streaming

   5. **Format Agnosticism**
      - Works with Gemini, OpenAI, custom LLMs
      - Converter pattern handles differences

   6. **Tool Discovery**
      - Built-in tools registered manually
      - External tools discovered dynamically
      - MCP servers discovered at runtime

   ---

   ## PATTERNS FOR MARM ADOPTION

   ### Pattern 1: Simple Read-Only Tool

   ```typescript
   interface MyToolParams {
     query: string;
   }

   class MyTool extends BaseDeclarativeTool<MyToolParams, ToolResult> {
     constructor(private config: Config) {
       super(
         'my_tool',
         'My Tool',
         'Description of what tool does',
         Kind.Read,  // Read-only, no confirmation needed
         {
           properties: {
             query: { type: 'string', description: 'Search query' }
           },
           required: ['query']
         }
       );
     }

     protected override createInvocation(params) {
       return new MyToolInvocation(this.config, params);
     }
   }

   class MyToolInvocation extends BaseToolInvocation<MyToolParams, ToolResult> {
     getDescription() {
       return `Searching for: ${this.params.query}`;
     }

     async execute(signal, updateOutput?) {
       const results = await search(this.params.query);
       return {
         llmContent: JSON.stringify(results),
         returnDisplay: formatResults(results)
       };
     }
   }
   ```

   ### Pattern 2: Tool With Confirmation

   ```typescript
   async shouldConfirmExecute(signal): Promise<ConfirmationDetails | false> {
     // If inherently safe, no confirmation
     if (this.isSafeOperation()) return false;

     // Otherwise ask user
     return {
       type: 'exec',
       title: 'Confirm Operation',
       command: this.params.operation,
       onConfirm: async (outcome) => {
         if (outcome === ToolConfirmationOutcome.ProceedAlways) {
           // Remember this approval
         }
       }
     };
   }
   ```

   ### Pattern 3: Tool With Streaming Output

   ```typescript
   class MyTool extends BaseDeclarativeTool {
     constructor() {
       super(
         'my_tool',
         // ... other params ...
         true,   // isOutputMarkdown
         true    // canUpdateOutput <- enables streaming
       );
     }

     async execute(signal, updateOutput?) {
       for (const chunk of getResults()) {
         updateOutput?.(chunk);  // Live update to UI
         await delay(100);
       }
       return finalResult;
     }
   }
   ```

   ---

   ## CRITICAL SUCCESS FACTORS

   1. **JSON Schema vs TypeScript**
      - Use JSON Schema in parameterSchema field
      - LLM needs schema to understand parameters

   2. **Validation is Multi-Layer**
      - JSON Schema validates structure
      - Custom validation checks business logic
      - Both must pass before invocation

   3. **Confirmation is NOT Approval**
      - Confirmation = "Tell user what will happen"
      - Tool still decides to approve/reject
      - Multiple approval modes (YOLO/PLAN/NORMAL)

   4. **Tool Results are Dual-Purpose**
      - llmContent: for LLM history (facts/data)
      - returnDisplay: for user UI (formatted/human)

   5. **Errors are Structured**
      - Don't just return error strings
      - Use ToolErrorType enum for context
      - LLM can understand and respond accordingly

   ---

   ## NEXT STEPS FOR MARM

   1. Adopt DeclarativeTool pattern for all memory operations
   2. Implement ToolRegistry for MARM CLI
   3. Add JSON Schema generation for memory search parameters
   4. Build confirmation workflow for memory mutations
   5. Format-agnostic API (support Gemini + OpenAI)
   6. Live streaming for search results
   7. Structured error types for memory operations

   EOF
   cat "C:\Users\lyell\Desktop\MARM-Systems\QWEN_CODE_ANALYSIS_PART1.md"
