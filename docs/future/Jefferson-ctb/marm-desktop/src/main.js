import { invoke } from '@tauri-apps/api/core';

// Security utilities for safe HTML handling
function sanitizeHTML(html) {
  const div = document.createElement('div');
  div.textContent = html;
  return div.innerHTML;
}

function safeSetInnerHTML(element, content) {
  if (typeof content === 'string' && content.includes('<')) {
    // Use iterative sanitization to prevent bypass attacks
    let sanitized = content;
    let previous;
    do {
      previous = sanitized;
      sanitized = sanitized.replace(/<[^>]*>/g, '');
    } while (sanitized !== previous);
    element.textContent = sanitized;
  } else {
    element.textContent = content;
  }
}

class MARMDesktop {
  constructor() {
    this.serverUrl = localStorage.getItem('marm-server-url') || '';
    this.isConnected = false;
    this.isAuthenticated = false;
    this.accessToken = null;
    this.activeTab = 'observer';
    this.activityLog = [];
    this.sessions = [];
    this.currentSession = null;
    this.lastActivityTimestamp = null;
    this.pollingInterval = null;
    this.isFirstRun = !localStorage.getItem('marm-setup-complete');
    
    // Show onboarding if first run
    if (this.isFirstRun) {
      this.showOnboarding();
    } else {
      this.initializeUI();
      this.setupEventHandlers();
      this.checkAuthStatus();
    }
  }

  initializeUI() {
    // Tab switching
    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', (e) => {
        const targetTab = e.target.getAttribute('data-tab');
        this.switchTab(targetTab);
      });
    });

    // Connect button
    document.getElementById('connect-btn').addEventListener('click', () => {
      this.connectToMARMServer();
    });

    // OAuth buttons
    document.getElementById('oauth-btn').addEventListener('click', () => {
      this.startOAuthFlow();
    });
    
    document.getElementById('logout-btn').addEventListener('click', () => {
      this.logout();
    });

    // Auto-connect if enabled and authenticated
    if (document.getElementById('auto-connect').checked) {
      setTimeout(() => {
        if (this.isAuthenticated) {
          this.connectToMARMServer();
        }
      }, 1000);
    }
  }

  setupEventHandlers() {
    // Settings changes
    document.getElementById('server-url').addEventListener('change', (e) => {
      this.serverUrl = e.target.value;
      localStorage.setItem('marm-server-url', this.serverUrl);
      this.validateServerUrl();
    });

    // Load saved settings
    if (this.serverUrl) {
      document.getElementById('server-url').value = this.serverUrl;
      this.validateServerUrl();
    }
  }

  switchTab(tabName) {
    // Remove active class from all tabs
    document.querySelectorAll('.tab').forEach(tab => {
      tab.classList.remove('active');
    });
    
    // Hide all tab content
    document.querySelectorAll('.tab-content').forEach(content => {
      content.style.display = 'none';
    });

    // Show selected tab
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`${tabName}-tab`).style.display = 'block';
    
    this.activeTab = tabName;

    // Load tab-specific content
    if (tabName === 'sessions') {
      this.loadSessions();
    } else if (tabName === 'observer' && this.isConnected) {
      // Refresh activity when switching to observer tab
      this.pollForUpdates();
    }
  }

  async checkAuthStatus() {
    try {
      const authStatus = await invoke('get_auth_status');
      this.isAuthenticated = authStatus.authenticated;
      this.accessToken = authStatus.token;
      this.updateAuthUI();
    } catch (error) {
      console.error('Error checking auth status:', error);
    }
  }

  updateAuthUI() {
    const authStatus = document.getElementById('auth-status');
    const oauthBtn = document.getElementById('oauth-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const connectBtn = document.getElementById('connect-btn');

    // Check if server URL is set
    if (!this.serverUrl || !this.isValidUrl(this.serverUrl)) {
      authStatus.textContent = '⚠️ Please set your FastMCP server URL first';
      authStatus.style.color = '#FF5722';
      oauthBtn.style.display = 'none';
      logoutBtn.style.display = 'none';
      connectBtn.disabled = true;
      connectBtn.textContent = 'Server URL Required';
      return;
    }

    if (this.isAuthenticated) {
      authStatus.textContent = '✅ Authenticated with FastMCP';
      authStatus.style.color = '#4CAF50';
      oauthBtn.style.display = 'none';
      logoutBtn.style.display = 'inline-block';
      connectBtn.disabled = false;
      connectBtn.textContent = 'Connect to MARM Server';
    } else {
      authStatus.textContent = '❌ Not authenticated - Click button to authenticate';
      authStatus.style.opacity = '0.7';
      oauthBtn.style.display = 'inline-block';
      logoutBtn.style.display = 'none';
      connectBtn.disabled = true;
      connectBtn.textContent = 'Authentication Required';
    }
  }

  async startOAuthFlow() {
    // Validate server URL before starting OAuth
    if (!this.serverUrl || !this.isValidUrl(this.serverUrl)) {
      alert('Please set a valid FastMCP server URL before authenticating.');
      this.switchTab('settings');
      return;
    }

    const oauthBtn = document.getElementById('oauth-btn');
    oauthBtn.disabled = true;
    oauthBtn.textContent = 'Authenticating...';
    oauthBtn.classList.add('loading');

    try {
      const result = await invoke('start_oauth_flow');
      if (result.success) {
        // OAuth completed successfully
        this.isAuthenticated = true;
        this.accessToken = result.token;
        this.updateAuthUI();
        
        // Show success message
        this.showNotification('✅ Authentication successful! You can now connect to your MARM server.', 'success');
      } else {
        throw new Error(result.error || 'OAuth failed');
      }
    } catch (error) {
      console.error('OAuth error:', error);
      this.showNotification(`❌ Authentication failed: ${error.message}`, 'error');
    } finally {
      oauthBtn.disabled = false;
      oauthBtn.textContent = 'Authenticate with FastMCP';
      oauthBtn.classList.remove('loading');
    }
  }

  async logout() {
    try {
      await invoke('logout');
      this.isAuthenticated = false;
      this.accessToken = null;
      this.isConnected = false;
      this.updateAuthUI();
      
      // Update connection status
      const observerStatus = document.getElementById('observer-status');
      observerStatus.textContent = 'Please authenticate to connect...';
      observerStatus.classList.add('loading');
      document.getElementById('activity-log').style.display = 'none';
    } catch (error) {
      console.error('Logout error:', error);
    }
  }

  async connectToMARMServer() {
    if (!this.isAuthenticated) {
      alert('Please authenticate with FastMCP first!');
      this.switchTab('settings');
      return;
    }

    const connectBtn = document.getElementById('connect-btn');
    const statusDiv = document.getElementById('observer-status');
    
    connectBtn.disabled = true;
    connectBtn.textContent = 'Connecting...';
    connectBtn.classList.add('loading');
    
    try {
      // Call Tauri backend to connect to MARM server with token
      const result = await invoke('connect_to_marm_server', { 
        url: this.serverUrl,
        token: this.accessToken
      });
      
      if (result.success) {
        this.isConnected = true;
        statusDiv.textContent = '✅ Connected to MARM MCP Server';
        connectBtn.textContent = 'Connected';
        connectBtn.classList.remove('loading');
        connectBtn.style.background = 'linear-gradient(45deg, #4CAF50, #45a049)';
        
        // Show activity log with enhanced monitoring status
        document.getElementById('activity-log').style.display = 'block';
        
        // Add monitoring status indicator
        const statusIndicator = document.createElement('div');
        statusIndicator.id = 'monitoring-status';
        statusIndicator.style.cssText = `
          background: rgba(76, 175, 80, 0.1);
          border: 1px solid rgba(76, 175, 80, 0.3);
          border-radius: 6px;
          padding: 10px;
          margin: 10px 0;
          text-align: center;
          font-size: 12px;
        `;
        statusIndicator.textContent = '🔴 Initializing real-time monitoring...';
        
        const activityLog = document.getElementById('activity-log');
        activityLog.insertBefore(statusIndicator, activityLog.firstChild);
        
        // Start listening for MARM activity
        this.startActivityMonitoring();
        
      } else {
        throw new Error(result.error || 'Connection failed');
      }
    } catch (error) {
      console.error('MARM connection error:', error);
      statusDiv.textContent = `❌ Connection failed: ${error.message}`;
      connectBtn.textContent = 'Retry Connection';
      connectBtn.classList.remove('loading');
      connectBtn.disabled = false;
    }
  }

  async startActivityMonitoring() {
    // Clear any existing polling interval
    if (this.pollingInterval) {
      clearInterval(this.pollingInterval);
    }
    
    // Initial load
    await this.pollForUpdates();
    
    // Update monitoring status
    const statusIndicator = document.getElementById('monitoring-status');
    if (statusIndicator) {
      statusIndicator.textContent = '🟢 Real-time monitoring active - Polling every 2 seconds';
      statusIndicator.style.background = 'rgba(76, 175, 80, 0.1)';
    }
    
    // Set up regular polling every 2 seconds
    this.pollingInterval = setInterval(async () => {
      await this.pollForUpdates();
    }, 2000);
  }
  
  async pollForUpdates() {
    try {
      // Poll for activity
      const activity = await invoke('get_marm_activity');
      if (activity && activity.length > 0) {
        this.updateActivityLog(activity);
        
        // Update last activity timestamp for incremental polling
        if (activity[0] && activity[0].timestamp) {
          this.lastActivityTimestamp = activity[0].timestamp;
        }
      }
      
      // Poll for session changes if we're on the sessions tab
      if (this.activeTab === 'sessions') {
        await this.refreshSessions();
      }
    } catch (error) {
      console.error('Error polling for updates:', error);
      
      // Update monitoring status on error
      const statusIndicator = document.getElementById('monitoring-status');
      if (statusIndicator) {
        statusIndicator.textContent = '🟡 Monitoring error - Retrying...';
        statusIndicator.style.background = 'rgba(255, 193, 7, 0.1)';
      }
      
      // If server is unreachable, update connection status
      if (error.message.includes('connect') || error.message.includes('timeout')) {
        this.handleConnectionLost();
      }
    }
  }

  updateActivityLog(activities) {
    const activityList = document.getElementById('activity-list');
    let newActivityCount = 0;
    
    activities.forEach(activity => {
      if (!this.activityLog.find(log => log.id === activity.id)) {
        this.activityLog.unshift(activity);
        newActivityCount++;
        
        const activityElement = document.createElement('div');
        
        // Different colors for different activity types
        const activityColors = {
          'marm_start': '#2196F3',
          'marm_start_auto': '#3F51B5',
          'marm_log_entry': '#4CAF50',
          'marm_notebook_add': '#FF9800',
          'marm_notebook_use': '#9C27B0',
          'session_switch': '#00BCD4',
          'default': '#607D8B'
        };
        
        const color = activityColors[activity.tool] || activityColors['default'];
        const isNewActivity = Date.now() - new Date(activity.timestamp).getTime() < 5000;
        
        activityElement.style.cssText = `
          background: ${isNewActivity ? 'rgba(76, 175, 80, 0.1)' : 'rgba(255, 255, 255, 0.05)'};
          border-radius: 8px;
          padding: 12px;
          margin: 8px 0;
          border-left: 4px solid ${color};
          transition: all 0.3s ease;
          ${isNewActivity ? 'box-shadow: 0 0 10px rgba(76, 175, 80, 0.3);' : ''}
          position: relative;
        `;
        
        // Add activity type icons
        const activityIcons = {
          'marm_start': '🚀',
          'marm_start_auto': '⚡',
          'marm_log_entry': '📝',
          'marm_notebook_add': '📚',
          'marm_notebook_use': '🔗',
          'session_switch': '🔄',
          'default': '🔧'
        };
        
        const icon = activityIcons[activity.tool] || activityIcons['default'];
        
        // Create activity element structure safely
        activityElement.textContent = ''; // Clear first
        
        if (isNewActivity) {
          const newBadge = document.createElement('div');
          newBadge.style.cssText = 'position: absolute; top: 5px; right: 10px; color: #4CAF50; font-size: 12px; animation: pulse 2s infinite;';
          newBadge.textContent = '● NEW';
          activityElement.appendChild(newBadge);
        }
        
        const mainDiv = document.createElement('div');
        mainDiv.style.cssText = 'display: flex; align-items: center; margin-bottom: 8px;';
        
        const iconSpan = document.createElement('span');
        iconSpan.style.cssText = 'font-size: 16px; margin-right: 8px;';
        iconSpan.textContent = icon;
        
        const infoDiv = document.createElement('div');
        
        const timeDiv = document.createElement('div');
        timeDiv.style.cssText = 'font-size: 12px; opacity: 0.7;';
        timeDiv.textContent = new Date(activity.timestamp).toLocaleString();
        
        const typeDiv = document.createElement('div');
        typeDiv.style.cssText = `font-weight: bold; color: ${color}; margin: 2px 0;`;
        typeDiv.textContent = this.formatActivityType(activity.tool);
        
        infoDiv.appendChild(timeDiv);
        infoDiv.appendChild(typeDiv);
        mainDiv.appendChild(iconSpan);
        mainDiv.appendChild(infoDiv);
        
        const descDiv = document.createElement('div');
        descDiv.style.cssText = 'font-size: 14px; margin-left: 24px;';
        descDiv.textContent = activity.description;
        
        activityElement.appendChild(mainDiv);
        activityElement.appendChild(descDiv);
        
        if (activity.session) {
          const sessionDiv = document.createElement('div');
          sessionDiv.style.cssText = `font-size: 12px; color: ${color}; margin-left: 24px; margin-top: 4px;`;
          sessionDiv.textContent = `📁 Session: ${activity.session}`;
          activityElement.appendChild(sessionDiv);
        }
        
        activityList.prepend(activityElement);
        
        // Remove 'new' styling after 5 seconds
        if (isNewActivity) {
          setTimeout(() => {
            activityElement.style.background = 'rgba(255, 255, 255, 0.05)';
            activityElement.style.boxShadow = 'none';
            const newBadge = activityElement.querySelector('div[style*="NEW"]');
            if (newBadge) newBadge.remove();
          }, 5000);
        }
      }
    });

    // Update activity counter if there are new activities
    if (newActivityCount > 0) {
      this.updateActivityStats(newActivityCount);
    }

    // Keep only last 50 activities
    if (this.activityLog.length > 50) {
      this.activityLog = this.activityLog.slice(0, 50);
      const children = activityList.children;
      for (let i = children.length - 1; i >= 50; i--) {
        children[i].remove();
      }
    }
  }
  
  formatActivityType(tool) {
    const toolNames = {
      'marm_start': 'MARM Started',
      'marm_start_auto': 'Auto-Initialize',
      'marm_log_entry': 'Log Entry',
      'marm_notebook_add': 'Notebook Add',
      'marm_notebook_use': 'Notebook Use',
      'session_switch': 'Session Switch',
      'default': 'MARM Activity'
    };
    return toolNames[tool] || toolNames['default'];
  }
  
  updateActivityStats(newCount) {
    // Update the observer tab title to show new activity
    const observerTab = document.querySelector('[data-tab="observer"]');
    if (observerTab && this.activeTab !== 'observer') {
      observerTab.textContent = `Observer (${newCount} new)`;
      observerTab.style.background = 'linear-gradient(45deg, #4CAF50, #45a049)';
      
      // Reset after 10 seconds
      setTimeout(() => {
        observerTab.textContent = 'Observer';
        observerTab.style.background = '';
      }, 10000);
    }
  }

  async loadSessions() {
    const sessionsList = document.getElementById('sessions-list');
    sessionsList.textContent = 'Loading sessions...';
    sessionsList.style.textAlign = 'center';
    sessionsList.style.padding = '20px';
    sessionsList.classList.add('loading');
    
    try {
      const sessions = await invoke('get_marm_sessions');
      this.sessions = sessions;
      
      if (sessions && sessions.length > 0) {
        // Create sessions list safely
        sessionsList.textContent = '';
        sessions.forEach(session => {
          const sessionDiv = document.createElement('div');
          sessionDiv.style.cssText = 'background: rgba(255,255,255,0.1); border-radius: 8px; padding: 15px; margin: 10px 0;';
          
          const title = document.createElement('h4');
          title.style.cssText = 'margin: 0 0 8px 0;';
          title.textContent = `${session.name} ${session.name === this.currentSession ? '(Current)' : ''}`;
          
          const createdDiv = document.createElement('div');
          createdDiv.style.cssText = 'font-size: 12px; opacity: 0.7;';
          createdDiv.textContent = `Created: ${new Date(session.created).toLocaleDateString()}`;
          
          const statsDiv = document.createElement('div');
          statsDiv.style.cssText = 'font-size: 12px; opacity: 0.7;';
          statsDiv.textContent = `Logs: ${session.log_count} | Notebook entries: ${session.notebook_count}`;
          
          const buttonsDiv = document.createElement('div');
          buttonsDiv.style.cssText = 'margin-top: 10px;';
          
          const switchBtn = document.createElement('button');
          const isCurrent = session.name === this.currentSession;
          switchBtn.disabled = isCurrent;
          switchBtn.style.cssText = `background: ${isCurrent ? '#666' : 'linear-gradient(45deg, #2196F3, #1976D2)'}; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: ${isCurrent ? 'default' : 'pointer'};`;
          switchBtn.textContent = 'Switch to Session';
          switchBtn.addEventListener('click', () => this.switchToSession(session.name));
          
          const detailsBtn = document.createElement('button');
          detailsBtn.style.cssText = 'background: linear-gradient(45deg, #FF9800, #F57C00); color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; margin-left: 8px;';
          detailsBtn.textContent = 'View Details';
          detailsBtn.addEventListener('click', () => this.viewSessionDetails(session.name));
          
          buttonsDiv.appendChild(switchBtn);
          buttonsDiv.appendChild(detailsBtn);
          
          sessionDiv.appendChild(title);
          sessionDiv.appendChild(createdDiv);
          sessionDiv.appendChild(statsDiv);
          sessionDiv.appendChild(buttonsDiv);
          
          sessionsList.appendChild(sessionDiv);
        });
      } else {
        const statusDiv = document.createElement('div');
        statusDiv.className = 'status';
        statusDiv.textContent = 'No MARM sessions found. Create one by using MARM commands in Claude Code.';
        sessionsList.textContent = '';
        sessionsList.appendChild(statusDiv);
      }
    } catch (error) {
      const errorDiv = document.createElement('div');
      errorDiv.className = 'status';
      errorDiv.textContent = `Error loading sessions: ${error.message}`;
      sessionsList.textContent = '';
      sessionsList.appendChild(errorDiv);
    }
  }
  
  async refreshSessions() {
    // Refresh sessions silently (no loading indicator)
    try {
      const sessions = await invoke('get_marm_sessions');
      if (JSON.stringify(sessions) !== JSON.stringify(this.sessions)) {
        await this.loadSessions();
      }
    } catch (error) {
      console.error('Error refreshing sessions:', error);
    }
  }

  async switchToSession(sessionName) {
    try {
      await invoke('switch_marm_session', { sessionName });
      this.currentSession = sessionName;
      
      // Update sessions list to show current session
      if (this.activeTab === 'sessions') {
        await this.loadSessions();
      }
      
      this.switchTab('direct');
      // Show success message
      const directTab = document.getElementById('direct-tab');
      const successMsg = document.createElement('div');
      successMsg.style.cssText = 'background: rgba(76, 175, 80, 0.2); padding: 10px; border-radius: 6px; margin: 10px 0; border: 1px solid rgba(76, 175, 80, 0.3);';
      successMsg.textContent = `✅ Switched to session: ${sessionName}`;
      directTab.prepend(successMsg);
      setTimeout(() => successMsg.remove(), 3000);
    } catch (error) {
      console.error('Error switching session:', error);
      alert(`Failed to switch session: ${error.message}`);
    }
  }
  
  async viewSessionDetails(sessionName) {
    // Create a modal to show detailed session information
    const modal = document.createElement('div');
    modal.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0, 0, 0, 0.8);
      display: flex;
      justify-content: center;
      align-items: center;
      z-index: 1000;
    `;
    
    const modalContent = document.createElement('div');
    modalContent.style.cssText = `
      background: linear-gradient(135deg, #1e1e2e, #2d2d3e);
      color: white;
      padding: 30px;
      border-radius: 12px;
      max-width: 80%;
      max-height: 80%;
      overflow-y: auto;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
      border: 1px solid rgba(255, 255, 255, 0.1);
    `;
    
    // Create modal content safely
    const title = document.createElement('h2');
    title.style.cssText = 'margin: 0 0 20px 0; color: #4CAF50;';
    title.textContent = `Session Details: ${sessionName}`;
    
    const contentDiv = document.createElement('div');
    contentDiv.id = 'session-detail-content';
    contentDiv.style.cssText = 'text-align: center; padding: 40px;';
    contentDiv.textContent = 'Loading session details...';
    contentDiv.classList.add('loading');
    
    const buttonDiv = document.createElement('div');
    buttonDiv.style.cssText = 'text-align: right; margin-top: 20px;';
    
    const closeBtn = document.createElement('button');
    closeBtn.id = 'close-modal';
    closeBtn.style.cssText = 'background: #f44336; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;';
    closeBtn.textContent = 'Close';
    
    buttonDiv.appendChild(closeBtn);
    modalContent.appendChild(title);
    modalContent.appendChild(contentDiv);
    modalContent.appendChild(buttonDiv);
    
    modal.appendChild(modalContent);
    document.body.appendChild(modal);
    
    // Close modal functionality
    document.getElementById('close-modal').onclick = () => {
      document.body.removeChild(modal);
    };
    
    modal.onclick = (e) => {
      if (e.target === modal) {
        document.body.removeChild(modal);
      }
    };
    
    // Load session details
    try {
      // For now, we'll create a detailed view from the session data we already have
      const session = this.sessions.find(s => s.name === sessionName);
      if (session) {
        const detailContent = document.getElementById('session-detail-content');
        // Create session details safely with proper DOM manipulation
        detailContent.textContent = '';
        detailContent.classList.remove('loading');
        
        const containerDiv = document.createElement('div');
        containerDiv.style.textAlign = 'left';
        
        // Session Overview section
        const overviewH3 = document.createElement('h3');
        overviewH3.style.cssText = 'color: #2196F3; margin-bottom: 15px;';
        overviewH3.textContent = '📊 Session Overview';
        
        const overviewDiv = document.createElement('div');
        overviewDiv.style.cssText = 'background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin-bottom: 20px;';
        
        // Create session info paragraphs safely
        const sessionData = [
          ['Session Name', session.name],
          ['Created', new Date(session.created).toLocaleString()],
          ['Log Entries', session.log_count.toString()],
          ['Notebook Entries', session.notebook_count.toString()],
          ['Status', session.name === this.currentSession ? '✅ Current Session' : 'Inactive']
        ];
        
        sessionData.forEach(([label, value], index) => {
          const p = document.createElement('p');
          const strong = document.createElement('strong');
          strong.textContent = `${label}: `;
          p.appendChild(strong);
          
          if (index === 4) { // Status field
            const statusSpan = document.createElement('span');
            statusSpan.textContent = value;
            statusSpan.style.color = session.name === this.currentSession ? '#4CAF50' : '#999';
            statusSpan.style.opacity = session.name === this.currentSession ? '1' : '0.7';
            p.appendChild(statusSpan);
          } else {
            const textNode = document.createTextNode(value);
            p.appendChild(textNode);
          }
          
          overviewDiv.appendChild(p);
        });
        
        // Recent Activity section
        const activityH3 = document.createElement('h3');
        activityH3.style.cssText = 'color: #FF9800; margin-bottom: 15px;';
        activityH3.textContent = '📝 Recent Activity';
        
        const activityDiv = document.createElement('div');
        activityDiv.style.cssText = 'background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin-bottom: 20px;';
        const activityElement = this.getSessionActivity(sessionName);
        activityDiv.appendChild(activityElement);
        
        // Real-time Sync section
        const syncH3 = document.createElement('h3');
        syncH3.style.cssText = 'color: #9C27B0; margin-bottom: 15px;';
        syncH3.textContent = '🔄 Real-time Sync';
        
        const syncDiv = document.createElement('div');
        syncDiv.style.cssText = 'background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px;';
        
        // Sync status paragraphs
        const syncData = [
          ['✅ Real-time monitoring: Active', null],
          ['📡 Connection status: ', this.isConnected ? 'Connected' : 'Disconnected'],
          [`🔄 Last update: ${this.lastActivityTimestamp ? new Date(this.lastActivityTimestamp).toLocaleTimeString() : 'Never'}`, null]
        ];
        
        syncData.forEach(([text, statusText]) => {
          const p = document.createElement('p');
          if (statusText) {
            p.textContent = text;
            const statusSpan = document.createElement('span');
            statusSpan.textContent = statusText;
            statusSpan.style.color = this.isConnected ? '#4CAF50' : '#f44336';
            p.appendChild(statusSpan);
          } else {
            p.textContent = text;
          }
          syncDiv.appendChild(p);
        });
        
        // Context synchronization note
        const contextP = document.createElement('p');
        contextP.style.cssText = 'margin-top: 10px; padding: 10px; background: rgba(76, 175, 80, 0.1); border-radius: 4px; font-size: 12px;';
        const contextStrong = document.createElement('strong');
        contextStrong.textContent = 'Context Synchronization: ';
        contextP.appendChild(contextStrong);
        contextP.appendChild(document.createTextNode('This session is synchronized with Claude Code in real-time. Any MARM commands executed in Claude Code will be reflected here automatically.'));
        syncDiv.appendChild(contextP);
        
        // Assemble the complete structure
        containerDiv.appendChild(overviewH3);
        containerDiv.appendChild(overviewDiv);
        containerDiv.appendChild(activityH3);
        containerDiv.appendChild(activityDiv);
        containerDiv.appendChild(syncH3);
        containerDiv.appendChild(syncDiv);
        
        detailContent.appendChild(containerDiv);
      } else {
        throw new Error('Session not found');
      }
    } catch (error) {
      const detailContent = document.getElementById('session-detail-content');
      const errorDiv = document.createElement('div');
      errorDiv.style.cssText = 'color: #f44336; text-align: center;';
      errorDiv.textContent = `❌ Error loading session details: ${error.message}`;
      detailContent.textContent = '';
      detailContent.appendChild(errorDiv);
    }
  }
  
  getSessionActivity(sessionName) {
    // This method now delegates to the safe element creation method
    return this.createSessionActivityElement(sessionName);
  }
  
  handleConnectionLost() {
    if (this.isConnected) {
      this.isConnected = false;
      const statusDiv = document.getElementById('observer-status');
      statusDiv.textContent = '❌ Connection lost to MARM server. Attempting to reconnect...';
      
      // Clear polling
      if (this.pollingInterval) {
        clearInterval(this.pollingInterval);
        this.pollingInterval = null;
      }
      
      // Try to reconnect after 5 seconds
      setTimeout(() => {
        if (!this.isConnected && this.isAuthenticated) {
          this.connectToMARMServer();
        }
      }, 5000);
    }
  }

  // Input validation methods
  isValidUrl(url) {
    if (!url || typeof url !== 'string') return false;
    
    // Remove any whitespace
    url = url.trim();
    
    try {
      const urlObj = new URL(url);
      // Only allow HTTPS URLs for security
      if (urlObj.protocol !== 'https:') return false;
      
      // Validate hostname format
      const hostname = urlObj.hostname;
      if (!hostname || hostname.length < 4) return false;
      
      // Block common malicious patterns
      const blockedPatterns = [
        'localhost', '127.0.0.1', '0.0.0.0', '::1',
        'file://', 'javascript:', 'data:',
        '<script', 'eval(', 'onclick='
      ];
      
      const lowerUrl = url.toLowerCase();
      if (blockedPatterns.some(pattern => lowerUrl.includes(pattern))) {
        return false;
      }
      
      // Must be a valid domain or IP
      return /^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(hostname) || 
             /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname);
    } catch (e) {
      return false;
    }
  }

  validateServerUrl() {
    const urlInput = document.getElementById('server-url');
    const statusDiv = document.getElementById('url-status');
    
    if (!urlInput) return;
    
    const url = urlInput.value.trim();
    if (!url) {
      if (statusDiv) statusDiv.textContent = '';
      return;
    }
    
    if (this.isValidUrl(url)) {
      if (statusDiv) {
        statusDiv.textContent = '✅ Valid URL';
        statusDiv.style.color = '#4CAF50';
      }
      urlInput.style.borderColor = '#4CAF50';
    } else {
      if (statusDiv) {
        statusDiv.textContent = '❌ Please enter a valid HTTPS URL';
        statusDiv.style.color = '#f44336';
      }
      urlInput.style.borderColor = '#f44336';
    }
  }

  // Add method to safely create elements with user content
  createSessionActivityElement(sessionName) {
    const container = document.createElement('div');
    
    const sessionActivity = this.activityLog.filter(activity => 
      activity.session === sessionName || (sessionName === this.currentSession && !activity.session)
    ).slice(0, 5);
    
    if (sessionActivity.length === 0) {
      const noActivity = document.createElement('p');
      noActivity.style.cssText = 'opacity: 0.7; text-align: center;';
      noActivity.textContent = 'No recent activity found for this session.';
      container.appendChild(noActivity);
      return container;
    }
    
    sessionActivity.forEach(activity => {
      const activityDiv = document.createElement('div');
      activityDiv.style.cssText = 'background: rgba(255,255,255,0.05); margin: 8px 0; padding: 10px; border-radius: 6px; border-left: 3px solid #4CAF50;';
      
      const timeDiv = document.createElement('div');
      timeDiv.style.cssText = 'font-size: 12px; opacity: 0.7;';
      timeDiv.textContent = new Date(activity.timestamp).toLocaleString();
      
      const toolDiv = document.createElement('div');
      toolDiv.style.cssText = 'font-weight: bold; color: #4CAF50; margin: 2px 0;';
      toolDiv.textContent = activity.tool;
      
      const descDiv = document.createElement('div');
      descDiv.style.cssText = 'font-size: 13px;';
      descDiv.textContent = activity.description;
      
      activityDiv.appendChild(timeDiv);
      activityDiv.appendChild(toolDiv);
      activityDiv.appendChild(descDiv);
      container.appendChild(activityDiv);
    });
    
    return container;
  }
}

// Initialize the app
window.app = new MARMDesktop();

console.log('MARM Desktop initialized');