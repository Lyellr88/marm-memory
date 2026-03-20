# MARM Desktop Security & Build Tests

This directory contains comprehensive unit tests that validate all security fixes and build improvements made to the MARM Desktop application.

## 🎯 Test Categories

### Security Tests (`security/`)
- **URL Validation** (`url-validation.test.js`) - Tests HTTPS enforcement, local access prevention, script injection blocking
- **DOM Manipulation** (`dom-manipulation.test.js`) - Validates innerHTML removal and XSS prevention measures
- **Console Logging** (`console-logging.test.js`) - Ensures sensitive information is not logged

### Build Tests (`build/`)
- **Rust Compilation** (`rust-compilation.test.js`) - Validates the critical Ok() → Ok(()) fix and prevents regression
- **GitHub Actions** (`github-actions.test.js`) - Tests CI/CD configuration and artifact generation

### Integration Tests (`integration/`)
- **Security Integration** (`security-integration.test.js`) - End-to-end security validation across components

## 🚀 Running Tests

### Install Dependencies
```bash
cd marm-desktop/tests
npm install
```

### Run All Tests
```bash
npm test
# OR from desktop root:
npm run test
```

### Run Specific Test Categories
```bash
npm run test:security    # Security tests only
npm run test:build       # Build configuration tests only
npm run test:coverage    # With coverage report
```

### Run Individual Test Files
```bash
npx jest security/url-validation.test.js
npx jest build/rust-compilation.test.js
```

## 🔍 Test Coverage

The tests cover all major security fixes implemented:

### 1. **Critical Build Fix** ✅
- Tests that the `Ok() → Ok(())` Rust compilation error is fixed
- Prevents regression of the build failure across all platforms
- Validates proper Rust error handling patterns

### 2. **HTML Injection Prevention** ✅
- Verifies all `innerHTML` usage has been eliminated
- Tests safe DOM manipulation patterns
- Validates XSS protection mechanisms

### 3. **Input Sanitization** ✅
- Tests comprehensive URL validation with security checks
- Validates HTTPS enforcement and local access prevention
- Tests script injection and bypass attempt prevention

### 4. **Console Security** ✅
- Ensures sensitive session data is not logged
- Validates that debug information has been properly sanitized
- Tests production-ready logging practices

### 5. **Integration Security** ✅
- End-to-end security flow validation
- Cross-component security consistency checks
- Defense-in-depth verification

## 📊 Example Test Results

```bash
PASS tests/security/url-validation.test.js (15.2s)
PASS tests/security/dom-manipulation.test.js (8.4s)
PASS tests/security/console-logging.test.js (5.1s)
PASS tests/build/rust-compilation.test.js (12.3s)
PASS tests/build/github-actions.test.js (6.7s)
PASS tests/integration/security-integration.test.js (9.8s)

Test Suites: 6 passed, 6 total
Tests:       89 passed, 89 total
Snapshots:   0 total
Time:        18.2s

==================== Coverage Summary ====================
Statements   : 85.2% ( 234/275 )
Branches     : 78.9% ( 123/156 )  
Functions    : 92.1% ( 47/51 )
Lines        : 86.7% ( 221/255 )
```

## 🛡️ Security Test Details

### URL Validation Tests
- **HTTPS Enforcement**: Rejects all HTTP URLs to prevent cleartext transmission
- **Local Access Prevention**: Blocks localhost, 127.0.0.1, file:// access attempts
- **Script Injection Prevention**: Blocks javascript:, data:, eval() injection attempts
- **Input Sanitization**: Handles null/undefined inputs, trims whitespace, validates domain format
- **Bypass Prevention**: Tests URL encoding bypass attempts and malformed constructions

### DOM Manipulation Tests  
- **innerHTML Prevention**: Confirms zero innerHTML assignments exist
- **Safe Construction**: Validates createElement/textContent usage patterns
- **Event Handler Security**: Ensures addEventListener is used instead of inline handlers
- **User Content Safety**: Tests safe handling of session names, descriptions, error messages

### Console Logging Tests
- **Sensitive Data Prevention**: No session context, API responses, or tokens in logs
- **Debug Sanitization**: Debug statements replaced with generic comments
- **Production Readiness**: No development flags or internal state exposure
- **Error Handling**: Safe error logging without exposing sensitive context

## 🔧 Test Configuration

- **Test Environment**: jsdom for DOM manipulation testing
- **Coverage**: HTML, LCOV, and text reports generated
- **Exclusions**: Tests are excluded from production builds via Cargo.toml and package.json
- **CI Integration**: Can be integrated into GitHub Actions for automated security validation

## 📁 Files Tested

### Desktop App
- `src/main.js` - Main application logic with security fixes
- `src-tauri/src/main.rs` - Rust backend with compilation fix
- `src-tauri/Cargo.toml` - Build configuration

### Webchat Components  
- `webchat/src/security/xssProtection.js` - XSS protection utilities
- `webchat/src/logic/session.js` - Session management (console logging fixes)
- `webchat/src/replicateHelper.js` - API helper (logging sanitization)

### Build Configuration
- `.github/workflows/build-desktop.yml` - GitHub Actions workflow
- `.github/dependabot.yml` - Dependency management

## 🚨 Security Regression Prevention

These tests serve as regression prevention by:

1. **Failing if innerHTML is reintroduced** - Tests scan for innerHTML assignments
2. **Catching URL validation bypass** - Comprehensive input validation tests  
3. **Detecting console data leaks** - Tests ensure no sensitive logging
4. **Preventing build regression** - Tests validate the critical Rust fix remains
5. **Enforcing security patterns** - Integration tests validate end-to-end security

## 💡 Adding New Tests

When adding new security features or fixes:

1. Add tests to the appropriate category (`security/`, `build/`, `integration/`)
2. Follow the existing test patterns and naming conventions
3. Include both positive and negative test cases
4. Test edge cases and bypass attempts
5. Update this README with new test descriptions

## 🔗 Related Documentation

- [Main Project README](../../../README.md)
- [Build Configuration](../../src-tauri/Cargo.toml)
- [GitHub Actions Workflow](../../../.github/workflows/build-desktop.yml)
- [Security Implementation](../../src/main.js)