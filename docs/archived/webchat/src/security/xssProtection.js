// xssProtection.js - XSS sanitization functions for secure HTML processing
// Future: DOMPurify/Sanitizer API integration planned

// ===== PERFORMANCE OPTIMIZATION =====
const REGEX_CACHE = {
    htmlEntities: /&(?:lt|gt|quot|#x0*3[ce]);?/gi,
    dangerousTags: /<(script|style)[^>]*>.*?<\/\1>/gis,
    svgElements: /<\/?(?:svg|animate|animateMotion|animateTransform|set|foreignObject|math|annotation-xml)[^>]*(?:\/>|>.*?<\/(?:svg|animate|animateMotion|animateTransform|set|foreignObject|math|annotation-xml)>)?/gis,
    metaRefresh: /<meta[^>]*(?:http-equiv\s*=\s*["']?refresh["']?|content\s*=\s*["'][^"']*(?:javascript|data):[^"']*["'])[^>]*\/?>/gis,
    formElements: /<\/?(?:iframe|object|embed|form|input|textarea|select)(?:\s[^>]*)?(?:\/>|>.*?<\/(?:iframe|object|embed|form|textarea|select)>)?/gis,
    dangerousButtons: /<button(?!\s[^>]*class\s*=\s*["'][^"']*code-window-copy-btn[^"']*["'])[^>]*>.*?<\/button>/gis,
    dangerousAttrs: /\s*(?:on\w+|formaction|srcdoc|background|lowsrc)\s*=\s*(?:["'][^"']*["']|[^"'\s>]*)|(?:javascript|vbscript|data):[^"'\s>]*|expression\s*\(|data\s*:\s*[^,;]*[;,]/gi
};

let tempElement = null;
function getTempElement() {
    if (!tempElement) {
        tempElement = document.createElement('div');
    }
    tempElement.innerHTML = '';
    return tempElement;
}

// ===== SANITIZATION FUNCTIONS =====
function sanitizeText(input) {
    if (typeof input !== 'string') return '';
    
    const div = getTempElement();
    div.textContent = input;
    const result = div.innerHTML;
    div.textContent = '';
    return result;
}

function sanitizeHTML(input) {
    if (typeof input !== 'string') return '';
    
    let sanitized = input;
    let previous;
    let attempts = 3; // Maximum attempts to prevent infinite loops
    
    // Multiple passes to prevent bypass techniques
    do {
        previous = sanitized;
        // Decode HTML entities first
        sanitized = sanitized.replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&#x0*3c;?/gi, '<').replace(/&#x0*3e;?/gi, '>');
        // Remove dangerous content
        sanitized = sanitized.replace(REGEX_CACHE.dangerousTags, '');
        sanitized = sanitized.replace(REGEX_CACHE.metaRefresh, '');
        sanitized = sanitized.replace(REGEX_CACHE.svgElements, '');
        sanitized = sanitized.replace(REGEX_CACHE.formElements, '');   
        sanitized = sanitized.replace(REGEX_CACHE.dangerousButtons, '');
        sanitized = sanitized.replace(REGEX_CACHE.dangerousAttrs, '');
        
        // Additional security patterns
        sanitized = sanitized.replace(/(?:javascript|vbscript|data|livescript|mocha):\s*[^\s>]*/gi, '');
        sanitized = sanitized.replace(/on[a-z]+\s*=\s*[^\s>]*/gi, '');
        
        attempts--;
    } while (sanitized !== previous && attempts > 0);
    return sanitized;
}

function sanitizeHTMLStrict(input) {
    if (typeof input !== 'string') return '';
    
    const allowedTags = ['p', 'br', 'strong', 'b', 'em', 'i', 'u', 'a', 'ul', 'ol', 'li', 'code', 'pre', 'span'];
    const allowedAttributes = {
        'a': ['href', 'title'],
        'code': ['class'],
        'pre': ['class'],
        'span': ['class']
    };
    
    let sanitized = sanitizeHTML(input);
    const temp = document.createElement('div');
    temp.innerHTML = sanitized;
    
    function cleanElement(element) {
        const tagName = element.tagName.toLowerCase();
        
        if (element.namespaceURI === "http://www.w3.org/2000/svg") {
            element.remove();
            return;
        }
        
        if (!allowedTags.includes(tagName)) {
            if (element.childNodes.length > 0) {
                element.replaceWith(...element.childNodes);
            } else {
                element.remove();
            }
            return;
        }
        
        const allowedAttrs = allowedAttributes[tagName] || [];
        Array.from(element.attributes).forEach(attr => {
            if (!allowedAttrs.includes(attr.name)) {
                element.removeAttribute(attr.name);
            }
        });
        
        if (tagName === 'a' && element.hasAttribute('href')) {
            const href = element.getAttribute('href');
            if (!href.match(/^https?:\/\//)) {
                element.removeAttribute('href');
            }
        }
        
        if (['code', 'pre', 'span'].includes(tagName) && element.hasAttribute('class')) {
            const className = element.getAttribute('class');
            if (!className.match(/^[a-zA-Z0-9\-_\s]+$/)) {
                element.removeAttribute('class');
            }
        }
        
        Array.from(element.children).forEach(cleanElement);
    }
    
    Array.from(temp.children).forEach(cleanElement);
    
    const svgCheck = temp.querySelectorAll('*');
    svgCheck.forEach(el => {
        if (el.namespaceURI === "http://www.w3.org/2000/svg") {
            el.remove();
        }
        if (el.tagName && ['foreignObject', 'math', 'annotation-xml'].includes(el.tagName.toLowerCase())) {
            el.remove();
        }
    });
    
    return temp.innerHTML;
}

// ===== DOM INSERTION FUNCTIONS =====
function safeInsertHTML(element, content, useSanitization = true) {
    if (!element || !content) return;
    
    if (useSanitization) {
        element.innerHTML = sanitizeHTML(content);
    } else {
        element.textContent = content;
    }
}

function insertChatMessage(container, message, isHTML = false) {
    if (!container || !message) return;
    
    const messageElement = document.createElement('div');
    messageElement.className = 'chat-message';
    
    if (isHTML) {
        messageElement.innerHTML = sanitizeHTMLStrict(message);
    } else {
        messageElement.textContent = message;
    }
    
    container.appendChild(messageElement);
    return messageElement;
}

// ===== MODULE EXPORTS =====
export {
    sanitizeText,
    sanitizeHTML,
    sanitizeHTMLStrict,
    safeInsertHTML,
    insertChatMessage
};

if (typeof window !== 'undefined') {
    const isDevelopment = typeof process !== 'undefined' && process.env?.NODE_ENV === 'development' ||
                         window.location?.hostname === 'localhost' ||
                         window.location?.hostname === '127.0.0.1' ||
                         window.location?.protocol === 'file:';
    
    if (isDevelopment) {
        window.__DEV_MARMSecurity = {
            sanitizeText,
            sanitizeHTML,
            sanitizeHTMLStrict,
            safeInsertHTML,
            insertChatMessage,
            _validateInput: (input) => {
                // Validation function for development
            }
        };
        
        window.MARMSecurity = window.__DEV_MARMSecurity;
    }
}
