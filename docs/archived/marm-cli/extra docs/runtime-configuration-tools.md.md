# 📌 STEP 1.0: Create Config Management & Agent Tuning Tools (45 mins)

**CRITICAL: Add these 2 tools from the start for user flexibility**

#### Tool 1: Config Update Tool

**New File:** `packages/core/src/tools/config-manager.ts`

```typescript
import fs from 'fs/promises';
import path from 'path';

interface SystemConfig {
  llm_endpoint: string;
  default_model: string;
  marm_db_path: string;
  temperature?: number;
  top_p?: number;
  repeat_penalty?: number;
}

const CONFIG_PATH = path.join(process.cwd(), 'config.json');

export async function updateConfiguration(params: {
  endpoint_url?: string;
  model_name?: string;
}): Promise<string> {
  /**
   * Updates system configuration for LLM endpoint and model.
   * Allows users to switch from Ollama to other providers or remote instances.
   */
  const configData: SystemConfig = JSON.parse(
    await fs.readFile(CONFIG_PATH, 'utf-8')
  );

  if (params.endpoint_url) {
    configData.llm_endpoint = params.endpoint_url;
  }
  if (params.model_name) {
    configData.default_model = params.model_name;
  }

  await fs.writeFile(CONFIG_PATH, JSON.stringify(configData, null, 2));

  return `Configuration updated. Endpoint: ${configData.llm_endpoint}, Model: ${configData.default_model}`;
}
```

#### Tool 2: Agent Tuning Tool

**New File:** `packages/core/src/tools/agent-tuner.ts`

```typescript
import fs from 'fs/promises';
import path from 'path';

const CONFIG_PATH = path.join(process.cwd(), 'config.json');

export async function tuneAgent(params: {
  temperature?: number;
  top_p?: number;
  repeat_penalty?: number;
}): Promise<string> {
  /**
   * Adjusts model inference parameters for coding tasks.
   * Lower temperature (0.2-0.5) = more deterministic code
   * Higher temperature (0.7-1.0) = more creative responses
   */
  const configData = JSON.parse(await fs.readFile(CONFIG_PATH, 'utf-8'));

  if (params.temperature !== undefined) {
    configData.temperature = params.temperature;
  }
  if (params.top_p !== undefined) {
    configData.top_p = params.top_p;
  }
  if (params.repeat_penalty !== undefined) {
    configData.repeat_penalty = params.repeat_penalty;
  }

  await fs.writeFile(CONFIG_PATH, JSON.stringify(configData, null, 2));

  return `Agent tuned. Temp: ${configData.temperature}, Top-P: ${configData.top_p}, Repeat Penalty: ${configData.repeat_penalty}`;
}
```

---

this is the converstation with gemini that sparked these 2 tools so might help later on -

What can i do to improve my experience, since we have tons of data about deepseek 2 14b what can i add to a docker image to make it overall more accurate and better at coding?

While you cannot architecturally turn DeepSeek V2 into V3 with a Docker image, you can significantly improve its accuracy and coding performance through configuration, integration, and prompt engineering. The Docker image is a vehicle for optimizing the environment and execution of the V2 model. 
Here are concrete steps you can take to make the most of DeepSeek 2 14B:
1. Optimize Inference Parameters
These settings control how the model generates responses and can drastically improve code quality and reduce errors (hallucinations):
Temperature: Lower the temperature for coding tasks. Code usually needs to be deterministic and logically correct, not creative. A range of 0.2 to 0.5 is often ideal.
Top_P/Top_K: Adjust these to keep the model focused on the most likely correct tokens. A top_p of around 0.8 and a top_k around 20-40 can improve output reliability.
Repetition Penalty: A slight penalty (e.g., 1.05) can prevent the model from getting stuck in loops, which is common during code generation.
Max Tokens: Ensure you give the model enough room to output the full code solution. Setting a high max_tokens (e.g., 4096 or more) prevents truncation errors.
2. Implement Effective Prompt Engineering 
How you talk to the model matters more than any other configuration tweak. The Coder models respond very well to structured prompts:
Explicit Role Setting: Start your system prompt with a clear instruction: "You are an expert software developer specializing in Python and JavaScript. You only output valid, executable code and clear instructions."
Use Thinking Modes/Chain of Thought: Encourage the model to reason before outputting code. Adding <thought> or [PLAN] tags instructs the model to generate a plan first, improving accuracy. DeepSeek models are known to respond well to this.
Structured Output Formats: Request output in a specific format (e.g., Markdown, JSON). For example: "Respond with the code block in a single markdown ```python ... ``` block. Do not include any explanations outside the code block."
Provide Context (RAG): The best way to improve accuracy on your specific codebase is to use a RAG (Retrieval-Augmented Generation) system. This involves fetching relevant files or documentation from your project and injecting them into the model's context window before it generates a response. This requires an agent framework (LangChain/LlamaIndex), not just Docker. 
3. Use an Optimized Runtime Environment (Docker)
While Docker won't change the model weights, it can ensure you are using the most efficient way to run those weights.
Use the vLLM Inference Engine: The DeepSeek Coder models benefit significantly from the vLLM inference engine, which handles the complex MoE architecture more efficiently than the standard HuggingFace transformers library. Your Docker image should ideally wrap vLLM.
Quantization: If the full FP16 version of the 14B model pushes your 12GB VRAM limit too hard, running a quantized version (e.g., using GGUF in Ollama) can make it run much smoother, trading a tiny bit of accuracy for speed and stability.
Leverage Ollama's Setup: Using the ollama Docker image is the easiest way to ensure an optimized setup with correct chat templates and minimal overhead. 
By focusing on these practical configuration and prompt strategies, you can maximize the performance of DeepSeek 2 14B within your hardware limits.



Now the next quesiton since i installed deepseek v2 14b locally do i have access to the directory to edit or add code?

Yes, you have access to the model's directory, but you cannot directly edit or add code to the model's weights themselves using standard text editing tools. The model files are compressed binaries containing the mathematical parameters (weights) and structure (GGUF format) and are not editable source code files. 
However, you can achieve your goal of improving the model's behavior using Ollama's configuration options:
1. Locating the Model Files
The files are typically stored in a hidden directory:
Windows: C:\Users\%username%\.ollama\models
Mac/Linux: ~/.ollama/models 
Inside, you will find a blobs folder containing the actual, large model files (e.g., the 14B deepseek file is around 9GB).
2. How to "Add Code" or Improve Behavior
You don't add code to the model file directly. Instead, you create a Modelfile in Ollama to wrap the existing model with specific instructions and parameters. This is how you implement the "enhancements" we discussed earlier.
Steps to Create a Custom Modelfile:
Create a new file named Modelfile (no extension) in a location you prefer (e.g., your Desktop).
Define your custom model using the base model as a starting point.Example Modelfile content for the DeepSeek V2 14B model:
dockerfile
FROM deepseek-r1:14b # This refers to the model you pulled with Ollama

# Set a highly specific system prompt for coding tasks
SYSTEM """You are an expert software developer specializing in clean, efficient code. 
You only provide the requested code in a single markdown block and strictly adhere to 
the user's instructions. First, plan your solution using a <PLAN> tag, then provide the code."""

# Set parameters for more deterministic, reliable coding output
PARAMETER temperature 0.3
PARAMETER top_p 0.8
PARAMETER repeat_penalty 1.1
Use code with caution.

Create the new custom model in Ollama using this Modelfile from your terminal:Navigate to the directory where you saved the Modelfile (e.g., cd Desktop) and run:
bash
ollama create deepseek-coder-enhanced -f ./Modelfile
Use code with caution.

 
3. Run Your Enhanced Model
Now you have a new custom model called deepseek-coder-enhanced that has the behavior tweaks applied every time it runs.
bash
ollama run deepseek-coder-enhanced
Use code with caution.

This approach allows you to customize the experience significantly using the existing weights, which is exactly how local LLM users optimize their setup.

---

plus the beauty of it is people can use any agent the machine can handle thats avaible locally so if someone has a tank of a build they can run a much higher parameter, can i add in a system tool that alters the code? like api endpoint it will point to local ollama but if someone wants to use something else the can just add the numbers in and it replaces the ollama numbers?

That's an excellent design principle: maximize user flexibility based on their available hardware. This is absolutely achievable and exactly how professional agent systems manage configurations.
Yes, you can build a system tool within your agent framework (the modified Qwen CLI) that allows the user to easily switch the API endpoint used by the application.
How to Implement a Configurable Endpoint Tool
You need two things: a configuration mechanism and a tool definition.
1. The Configuration Mechanism (The "Numbers" to Change)
Instead of hardcoding http://localhost:11434 into every file, define the endpoint URL and the default model name in a central configuration file.
Example config.json:
json
{
  "llm_endpoint": "http://localhost:11434",
  "default_model": "MFDoom/deepseek-coder-v2-tool-calling:16b",
  "marm_db_path": "./marm_data.db"
}
Use code with caution.

Your entire application will read from this config.json when making API calls.
2. The System Tool (The "Alter Code" Function)
You can define a tool within your Qwen agent framework that allows the AI—or the user via the AI—to alter that configuration file.
Tool Definition (Example in the language you are using, likely Python):
python
def update_configuration(endpoint_url: str = None, model_name: str = None):
    """
    Updates the system configuration file for the AI agent. 
    Use this tool to switch to a different LLM endpoint or model.
    """
    import json
    with open('config.json', 'r+') as f:
        config_data = json.load(f)
        if endpoint_url:
            config_data['llm_endpoint'] = endpoint_url
        if model_name:
            config_data['default_model'] = model_name
        
        f.seek(0)  # Rewind file pointer to the beginning
        json.dump(config_data, f, indent=4)
        f.truncate() # Remove remaining part
    
    return f"Configuration updated. New endpoint: {config_data['llm_endpoint']}, New model: {config_data['default_model']}"

# This function is now exposed as a tool to the LLM agent
Use code with caution.

The User Experience
User with 12GB VRAM: Starts the system, uses the default localhost endpoint with deepseek-v2.
User with 48GB VRAM (The Tank Build): Can ask the AI: "Switch the system configuration to use the deepseek-v3 model weights hosted on my other local server at http://192.168.1.50:8000."
The agent calls the update_configuration tool, changes the config.json file, and subsequent calls use the new, larger model.
This makes your system highly flexible and scalable for different users' hardware capabilities. It perfectly fits your philosophy of a local, customizable, powerful agent.

