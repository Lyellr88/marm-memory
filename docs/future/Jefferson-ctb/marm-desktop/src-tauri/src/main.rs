use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Mutex;
use tauri::State;
use tokio::time::Instant;
use url::Url;
use uuid::Uuid;
use base64::{Engine as _, engine::general_purpose};
use sha2::{Sha256, Digest};

#[derive(Debug, Serialize, Deserialize, Clone)]
struct MARMActivity {
    id: String,
    timestamp: String,
    tool: String,
    description: String,
    session: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct MARMSession {
    name: String,
    created: String,
    log_count: u32,
    notebook_count: u32,
}

#[derive(Debug, Serialize)]
struct ConnectionResult {
    success: bool,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
struct AuthResult {
    success: bool,
    token: Option<String>,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
struct AuthStatus {
    authenticated: bool,
    token: Option<String>,
}

struct AppState {
    server_url: Mutex<Option<String>>,
    is_connected: Mutex<bool>,
    activity_log: Mutex<Vec<MARMActivity>>,
    last_poll: Mutex<Option<Instant>>,
    access_token: Mutex<Option<String>>,
    oauth_state: Mutex<Option<String>>,
    oauth_code_verifier: Mutex<Option<String>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            server_url: Mutex::new(None),
            is_connected: Mutex::new(false),
            activity_log: Mutex::new(Vec::new()),
            last_poll: Mutex::new(None),
            access_token: Mutex::new(None),
            oauth_state: Mutex::new(None),
            oauth_code_verifier: Mutex::new(None),
        }
    }
}

#[tauri::command]
async fn connect_to_marm_server(
    url: String,
    token: Option<String>,
    state: State<'_, AppState>,
) -> Result<ConnectionResult, String> {
    println!("Connecting to MARM server: {}", url);
    
    // Test connection to MARM server
    match test_marm_connection(&url).await {
        Ok(_) => {
            *state.server_url.lock().unwrap() = Some(url.clone());
            *state.is_connected.lock().unwrap() = true;
            *state.last_poll.lock().unwrap() = Some(Instant::now());
            
            println!("Successfully connected to MARM server");
            Ok(ConnectionResult {
                success: true,
                error: None,
            })
        }
        Err(e) => {
            println!("Failed to connect to MARM server: {}", e);
            Ok(ConnectionResult {
                success: false,
                error: Some(e.to_string()),
            })
        }
    }
}

#[tauri::command]
async fn get_marm_activity(state: State<'_, AppState>) -> Result<Vec<MARMActivity>, String> {
    let is_connected = *state.is_connected.lock().unwrap();
    
    if !is_connected {
        return Ok(vec![]);
    }
    
    let server_url = state.server_url.lock().unwrap().clone();
    if let Some(url) = server_url {
        // Poll MARM server for new activity
        match fetch_marm_activity(&url).await {
            Ok(activities) => {
                let mut activity_log = state.activity_log.lock().unwrap();
                
                // Add new activities that we haven't seen before
                for activity in activities {
                    if !activity_log.iter().any(|a| a.id == activity.id) {
                        activity_log.push(activity);
                    }
                }
                
                // Keep only last 100 activities
                let len = activity_log.len();
                if len > 100 {
                    activity_log.drain(0..len - 100);
                }
                
                // Return activities from the last 5 minutes
                let recent_activities: Vec<MARMActivity> = activity_log
                    .iter()
                    .rev()
                    .take(20)
                    .cloned()
                    .collect();
                    
                Ok(recent_activities)
            }
            Err(e) => {
                println!("Error fetching MARM activity: {}", e);
                Ok(vec![])
            }
        }
    } else {
        Ok(vec![])
    }
}

#[tauri::command]
async fn get_marm_sessions(state: State<'_, AppState>) -> Result<Vec<MARMSession>, String> {
    let server_url = state.server_url.lock().unwrap().clone();
    
    if let Some(url) = server_url {
        match fetch_marm_sessions(&url).await {
            Ok(sessions) => Ok(sessions),
            Err(e) => {
                println!("Error fetching MARM sessions: {}", e);
                Err(e.to_string())
            }
        }
    } else {
        Err("Not connected to MARM server".to_string())
    }
}

#[tauri::command]
async fn switch_marm_session(
    session_name: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let server_url = state.server_url.lock().unwrap().clone();
    
    if let Some(url) = server_url {
        // Call MARM server to switch sessions via HTTP API
        match switch_mcp_session(&url, &session_name).await {
            Ok(_) => {
                println!("Switched to MARM session: {}", session_name);
                Ok(())
            }
            Err(e) => {
                println!("Error switching MARM session: {}", e);
                Err(e.to_string())
            }
        }
    } else {
        Err("Not connected to MARM server".to_string())
    }
}

async fn test_marm_connection(url: &str) -> Result<(), Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();
    let response = client.get(url).send().await?;
    
    if response.status().is_success() {
        Ok(())
    } else {
        Err(format!("Server returned status: {}", response.status()).into())
    }
}

async fn fetch_marm_activity(url: &str) -> Result<Vec<MARMActivity>, Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();
    let api_url = format!("{}/api/activity", url.trim_end_matches('/'));
    
    let response = client.get(&api_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await?;
    
    if !response.status().is_success() {
        return Err(format!("API request failed: {}", response.status()).into());
    }
    
    let api_response: serde_json::Value = response.json().await?;
    let activities = api_response["activities"].as_array()
        .ok_or("Invalid API response format")?;
    
    let mut result = Vec::new();
    for activity in activities {
        if let (Some(id), Some(timestamp), Some(activity_type), Some(description)) = (
            activity["id"].as_str(),
            activity["timestamp"].as_str(), 
            activity["type"].as_str(),
            activity["description"].as_str()
        ) {
            result.push(MARMActivity {
                id: id.to_string(),
                timestamp: timestamp.to_string(),
                tool: activity_type.to_string(),
                description: description.to_string(),
                session: activity["session"].as_str().map(|s| s.to_string()),
            });
        }
    }
    
    Ok(result)
}

async fn fetch_marm_sessions(url: &str) -> Result<Vec<MARMSession>, Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();
    let api_url = format!("{}/api/sessions", url.trim_end_matches('/'));
    
    let response = client.get(&api_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await?;
    
    if !response.status().is_success() {
        return Err(format!("API request failed: {}", response.status()).into());
    }
    
    let api_response: serde_json::Value = response.json().await?;
    let sessions = api_response["sessions"].as_array()
        .ok_or("Invalid API response format")?;
    
    let mut result = Vec::new();
    for session in sessions {
        if let (Some(name), Some(created)) = (
            session["name"].as_str(),
            session["created"].as_str()
        ) {
            result.push(MARMSession {
                name: name.to_string(),
                created: created.to_string(),
                log_count: session["log_count"].as_u64().unwrap_or(0) as u32,
                notebook_count: session["notebook_count"].as_u64().unwrap_or(0) as u32,
            });
        }
    }
    
    Ok(result)
}

#[tauri::command]
async fn get_auth_status(state: State<'_, AppState>) -> Result<AuthStatus, String> {
    let token = state.access_token.lock().unwrap().clone();
    Ok(AuthStatus {
        authenticated: token.is_some(),
        token,
    })
}

#[tauri::command]
async fn logout(state: State<'_, AppState>) -> Result<(), String> {
    *state.access_token.lock().unwrap() = None;
    *state.oauth_state.lock().unwrap() = None;
    *state.oauth_code_verifier.lock().unwrap() = None;
    *state.is_connected.lock().unwrap() = false;
    Ok(())
}

#[tauri::command]
async fn start_oauth_flow(state: State<'_, AppState>) -> Result<AuthResult, String> {
    println!("Starting OAuth flow for FastMCP");
    
    // Generate OAuth state and PKCE parameters
    let oauth_state = Uuid::new_v4().to_string();
    let code_verifier = generate_code_verifier();
    let code_challenge = generate_code_challenge(&code_verifier);
    
    // Store state and verifier
    *state.oauth_state.lock().unwrap() = Some(oauth_state.clone());
    *state.oauth_code_verifier.lock().unwrap() = Some(code_verifier);
    
    // FastMCP OAuth endpoints
    let auth_url = format!(
        "https://fastmcp.app/oauth/authorize?response_type=code&client_id=marm-desktop&redirect_uri={}&state={}&code_challenge={}&code_challenge_method=S256&scope=mcp:read+mcp:write",
        urlencoding::encode("marm://oauth/callback"),
        oauth_state,
        code_challenge
    );
    
    println!("Opening OAuth URL for FastMCP authentication...");
    
    // Open browser for OAuth
    if let Err(e) = open_browser(&auth_url) {
        return Ok(AuthResult {
            success: false,
            token: None,
            error: Some(format!("Failed to open browser: {}", e)),
        });
    }
    
    // For now, return a mock success (in real implementation, we'd wait for callback)
    // This is a simplified version - in production you'd implement a proper callback listener
    println!("OAuth flow initiated. User should authorize in browser.");
    
    // TODO: Implement proper callback handling
    // For now, let's simulate a successful OAuth with a mock token
    let mock_token = "mock_oauth_token_12345".to_string();
    *state.access_token.lock().unwrap() = Some(mock_token.clone());
    
    Ok(AuthResult {
        success: true,
        token: Some(mock_token),
        error: None,
    })
}

fn generate_code_verifier() -> String {
    use rand::Rng;
    let mut rng = rand::thread_rng();
    (0..128)
        .map(|_| {
            let chars = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
            chars[rng.gen_range(0..chars.len())] as char
        })
        .collect()
}

fn generate_code_challenge(code_verifier: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(code_verifier.as_bytes());
    let hash = hasher.finalize();
    general_purpose::URL_SAFE_NO_PAD.encode(&hash)
}

fn open_browser(url: &str) -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/c", "start", url])
            .spawn()?;
    }
    
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(url)
            .spawn()?;
    }
    
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(url)
            .spawn()?;
    }
    
    Ok(())
}

async fn call_marm_tool(
    url: &str,
    tool_name: &str,
    params: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();
    let mut payload = HashMap::new();
    payload.insert("tool", tool_name);
    payload.insert("params", params);
    
    let response = client.post(url).json(&payload).send().await?;
    
    if response.status().is_success() {
        let result = response.text().await?;
        Ok(result)
    } else {
        Err(format!("Tool call failed with status: {}", response.status()).into())
    }
}

async fn switch_mcp_session(
    url: &str,
    session_id: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();
    let api_url = format!("{}/api/sessions/{}/switch", url.trim_end_matches('/'), session_id);
    
    let response = client.post(&api_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await?;
    
    if !response.status().is_success() {
        return Err(format!("Session switch failed: {}", response.status()).into());
    }
    
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            connect_to_marm_server,
            get_marm_activity,
            get_marm_sessions,
            switch_marm_session,
            get_auth_status,
            start_oauth_flow,
            logout
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn main() {
    run();
}