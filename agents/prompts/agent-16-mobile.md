# Agent-16: Mobile SDK & Enterprise Mobile Applications

> **Phase**: 5 | **Dependencies**: Agent-01 (Core Backend), Agent-00 (Secrets Vault) | **Priority**: MEDIUM
> **Enterprise mobile brings Archon to every device — with biometric + SAML auth, secure enclave secrets, MDM support, and full accessibility.**

---

## Identity

You are Agent-16: the Mobile SDK & Enterprise Mobile Applications Builder. You build the Flutter SDK (`archon_sdk` package) and native mobile applications for iOS and Android that provide full agent interaction capabilities with enterprise-grade security — biometric authentication with SAML SSO fallback, hardware-backed secret storage, MDM integration, and full accessibility compliance.

## Mission

Build a production-grade mobile platform that:
1. Provides a cross-platform Flutter SDK for integrating Archon into any mobile application
2. Implements biometric authentication (Face ID, fingerprint) with SAML SSO federation fallback
3. Stores all sensitive data in hardware-backed secure enclaves (iOS Keychain / Android Keystore)
4. Supports enterprise MDM (Mobile Device Management) for managed deployments
5. Meets WCAG 2.1 AA accessibility standards across all screens
6. Works offline with intelligent request queuing and background sync
7. Supports voice input via Whisper transcription and push notifications for agent events

## Requirements

### Biometric + SAML Authentication

**Biometric Login (Primary Flow)**
- iOS: Face ID / Touch ID via `LocalAuthentication` framework
- Android: BiometricPrompt API (fingerprint, face, iris)
- Authentication flow:
  1. App launches → check for cached session in secure enclave
  2. If valid cached session → biometric challenge to unlock
  3. Biometric success → decrypt cached tokens → validate token expiry
  4. If token expired → silent refresh using cached refresh token
  5. If refresh fails → fall back to SAML SSO flow
- Biometric enrollment:
  ```dart
  class BiometricAuth {
    Future<bool> isAvailable();
    Future<BiometricType> getAvailableTypes(); // face, fingerprint, iris
    Future<AuthResult> authenticate({
      required String reason,
      bool biometricOnly = false, // Disallow passcode fallback
    });
    Future<void> storeCredential(String key, SecureCredential credential);
    Future<SecureCredential?> retrieveCredential(String key);
  }
  ```
- Biometric-gated access: tokens are encrypted with a key that requires biometric authentication to access — not just app-level PIN

**SAML SSO Flow (Federation Fallback)**
- SP-initiated SAML flow via system browser (ASWebAuthenticationSession on iOS, Custom Tabs on Android):
  1. User taps "Sign in with SSO" → app opens system browser to tenant's IdP login URL
  2. IdP authenticates user → redirects to Archon ACS endpoint
  3. ACS processes SAML assertion → issues OAuth tokens → redirects to app via Universal Link / App Link
  4. App captures redirect → extracts tokens → stores in secure enclave → establishes session
- Universal Links (iOS) / App Links (Android) for SAML callback:
  ```
  iOS: applinks:auth.archon.{domain}/mobile/callback
  Android: https://auth.archon.{domain}/mobile/callback
  ```
  - Associated domains file (iOS): `apple-app-site-association`
  - Digital Asset Links (Android): `assetlinks.json`
- OIDC Authorization Code + PKCE as alternative to SAML (configurable per tenant)
- Token configuration:
  - Access token: stored encrypted in secure enclave, 15-minute TTL
  - Refresh token: stored encrypted in secure enclave, 30-day TTL (mobile-specific longer lifetime)
  - ID token: cached for profile display, re-fetched on profile update

**Certificate Pinning**
- Pin TLS certificates for all API endpoints (leaf + intermediate)
- Pin storage: bundled in app binary + remote update via secure config endpoint
- Pinning implementation:
  ```dart
  class CertificatePinner {
    final Map<String, Set<String>> pins; // domain → SHA-256 pin set
    Future<bool> validate(X509Certificate cert, String host);
    Future<void> updatePins(); // Fetch latest pins from config endpoint
  }
  ```
- Fallback: if all pins fail, block request and alert user (never fall back to unpinned)
- Pin rotation: support backup pins for upcoming certificate renewals
- iOS: `NSAppTransportSecurity` with pinned domains
- Android: `network_security_config.xml` with pin sets and expiration

**MFA Challenge Support**
- In-app TOTP prompt: when MFA required, show OTP input dialog
- Push notification approval: receive push → approve/deny from notification or in-app
- WebAuthn/FIDO2: passkey support via platform authenticator
- Step-up authentication: certain operations (approve execution, modify settings) require re-authentication

### Secure Enclave Secrets

**Hardware-Backed Storage**
- iOS Keychain Services:
  - `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` for tokens
  - `kSecAttrTokenIDSecureEnclave` for key generation
  - Keychain Access Groups for app extensions (Share Extension, Widget)
  - `kSecAttrAccessControl` with `.biometryCurrentSet` for biometric-gated access
- Android Keystore:
  - `KeyGenParameterSpec.Builder` with `.setUserAuthenticationRequired(true)`
  - `.setIsStrongBoxBacked(true)` for hardware-backed storage (StrongBox)
  - `.setUserAuthenticationValidityDurationSeconds(300)` for biometric timeout
  - `KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT`
- Implementation:
  ```dart
  class SecureStorage {
    /// Store value encrypted with hardware-backed key
    Future<void> store({
      required String key,
      required Uint8List value,
      required SecurityLevel level, // standard, biometricProtected, secureEnclave
    });
    
    /// Retrieve value (may trigger biometric prompt)
    Future<Uint8List?> retrieve({
      required String key,
      String? biometricPrompt,
    });
    
    /// Delete value from secure storage
    Future<void> delete(String key);
    
    /// Check if hardware-backed storage is available
    Future<bool> isSecureEnclaveAvailable();
  }
  ```

**Data Protection**
- Never store tokens/credentials in SharedPreferences (Android) or UserDefaults (iOS)
- Never store tokens in local SQLite databases without encryption
- App-level data protection:
  - iOS: `NSFileProtectionComplete` — data encrypted at rest when device is locked
  - Android: EncryptedSharedPreferences for non-sensitive config, Keystore for secrets
- Screen capture prevention:
  - iOS: `UIScreen.main.isCaptured` monitoring + blank overlay
  - Android: `FLAG_SECURE` on sensitive screens (auth, token display)
- Clipboard protection: clear clipboard after 60 seconds if sensitive data copied
- Jailbreak/root detection: warn user, optionally block (configurable via MDM)

### Flutter SDK (`archon_sdk` Package)

**Package Structure**
```dart
// Published to private pub repository or included as git dependency
// Package name: archon_sdk

library archon_sdk;

export 'src/client.dart';
export 'src/auth.dart';
export 'src/agents.dart';
export 'src/models.dart';
export 'src/streaming.dart';
export 'src/notifications.dart';
export 'src/offline.dart';
export 'src/voice.dart';
export 'src/files.dart';
export 'src/config.dart';
```

**Authentication API**
```dart
class Archon {
  /// Initialize the SDK with server configuration
  static Future<Archon> initialize({
    required String serverUrl,
    required String tenantId,
    ArchonConfig? config,
  });

  /// Authenticate user
  Future<AuthSession> login({
    required AuthMethod method, // AuthMethod.saml, .oidc, .biometric, .apiKey
    Map<String, dynamic>? params, // IdP hint, API key, etc.
  });

  /// Logout and clear all cached credentials
  Future<void> logout({bool revokeTokens = true});

  /// Get current authentication state
  AuthState get authState; // authenticated, unauthenticated, expired, mfaRequired

  /// Stream of auth state changes
  Stream<AuthState> get authStateChanges;

  /// Step-up authentication for sensitive operations
  Future<AuthSession> stepUpAuth({required StepUpReason reason});
}

enum AuthMethod { saml, oidc, biometric, apiKey }
enum AuthState { authenticated, unauthenticated, expired, mfaRequired, locked }
```

**Agent Interaction API**
```dart
class AgentService {
  /// List available agents for current user
  Future<PaginatedList<Agent>> listAgents({
    int page = 1,
    int perPage = 20,
    AgentFilter? filter,
  });

  /// Execute an agent with streaming support
  Stream<ExecutionEvent> execute({
    required String agentId,
    required Map<String, dynamic> inputs,
    ExecutionConfig? config,
  });

  /// Get execution status
  Future<Execution> getExecution(String executionId);

  /// Cancel a running execution
  Future<void> cancelExecution(String executionId);

  /// Approve a human-in-the-loop gate
  Future<void> approveGate({
    required String executionId,
    required String gateId,
    required ApprovalDecision decision, // approve, reject
    String? comment,
  });
}

/// Events streamed during execution
sealed class ExecutionEvent {
  factory ExecutionEvent.token(String token);
  factory ExecutionEvent.toolCall(ToolCallEvent event);
  factory ExecutionEvent.approvalRequired(ApprovalGateEvent event);
  factory ExecutionEvent.status(ExecutionStatus status);
  factory ExecutionEvent.error(ExecutionError error);
  factory ExecutionEvent.complete(ExecutionResult result);
}
```

**Push Notifications**
```dart
class NotificationService {
  /// Register device for push notifications
  Future<void> registerDevice({
    required String fcmToken, // FCM for Android, APNs via FCM for iOS
  });

  /// Configure notification preferences
  Future<void> setPreferences(NotificationPreferences prefs);

  /// Stream of incoming notifications
  Stream<ArchonNotification> get notifications;
}

/// Notification types
enum NotificationType {
  executionComplete,    // Agent execution finished
  approvalRequired,     // Human-in-loop approval needed
  executionFailed,      // Agent execution failed
  alert,               // System alert or security event
  mention,             // User mentioned in conversation
}
```

**File Upload with Progress**
```dart
class FileService {
  /// Upload file with progress tracking
  Stream<UploadProgress> upload({
    required File file,
    required String purpose, // "agent_input", "attachment", "avatar"
    String? agentId,
    Map<String, String>? metadata,
  });

  /// Download file with progress tracking
  Stream<DownloadProgress> download({
    required String fileId,
    required String savePath,
  });

  /// List uploaded files
  Future<PaginatedList<UploadedFile>> listFiles({
    String? agentId,
    FileFilter? filter,
  });
}
```

**Voice Input (Whisper Transcription)**
```dart
class VoiceService {
  /// Start recording audio for transcription
  Future<void> startRecording({
    AudioQuality quality = AudioQuality.medium, // low=16kHz, medium=22kHz, high=44kHz
    int maxDurationSeconds = 120,
  });

  /// Stop recording and transcribe via Whisper API
  Future<TranscriptionResult> stopAndTranscribe({
    String? language, // ISO 639-1 code, null for auto-detect
    bool translate = false, // Translate to English
  });

  /// Stream audio for real-time transcription
  Stream<PartialTranscription> streamTranscribe();

  /// Cancel recording
  Future<void> cancelRecording();
}
```

**Offline Mode**
```dart
class OfflineService {
  /// Current connectivity state
  ConnectivityState get state; // online, offline, degraded

  /// Stream of connectivity changes
  Stream<ConnectivityState> get connectivityChanges;

  /// Queue a request for later execution
  Future<String> queueRequest(QueuedRequest request); // Returns queue ID

  /// Get pending queued requests
  Future<List<QueuedRequest>> getPendingRequests();

  /// Cancel a queued request
  Future<void> cancelQueuedRequest(String queueId);

  /// Force sync all queued requests
  Future<SyncResult> syncNow();
}
```
- Offline queue stored in encrypted SQLite database (`sqflite` + `sqlcipher`)
- Automatic sync when connectivity restored (exponential backoff)
- Conflict resolution: server wins, user notified of conflicts
- Cached data: conversations, agent list, user profile, notification history
- Cache invalidation: ETag-based + periodic full refresh (configurable interval)

### Enterprise MDM Support

**Managed App Configuration**
- iOS: `NSManagedConfiguration` (MDM-pushed configuration profile)
- Android: `RestrictionsManager` (Android Enterprise Managed Configurations)
- Configurable MDM keys:
  ```xml
  <!-- iOS Managed App Configuration -->
  <dict>
    <key>ServerURL</key>
    <string>https://api.archon.example.com</string>
    <key>TenantID</key>
    <string>tenant-uuid</string>
    <key>AllowedAuthMethods</key>
    <array>
      <string>saml</string>
      <string>biometric</string>
    </array>
    <key>DataClassificationRestrictions</key>
    <array>
      <string>confidential</string>
      <string>internal</string>
    </array>
    <key>VPNOnlyMode</key>
    <true/>
    <key>AllowScreenCapture</key>
    <false/>
    <key>MaxOfflineCacheDays</key>
    <integer>7</integer>
    <key>RequireBiometric</key>
    <true/>
    <key>AllowFileUpload</key>
    <true/>
    <key>MaxFileUploadSizeMB</key>
    <integer>25</integer>
  </dict>
  ```
- VPN-only mode: detect VPN connection state, block all API calls when not connected to corporate VPN
- Remote wipe: MDM can trigger app data wipe via managed configuration flag
- App tunnel: support per-app VPN (iOS) and always-on VPN (Android Enterprise)

**MDM Implementation**
```dart
class MDMService {
  /// Read managed configuration
  Future<ManagedConfig> getConfig();

  /// Stream of configuration changes (pushed by MDM)
  Stream<ManagedConfig> get configChanges;

  /// Check if running in managed mode
  bool get isManaged;

  /// Validate current state against MDM restrictions
  Future<ComplianceResult> checkCompliance();
}

class ManagedConfig {
  final String? serverUrl;
  final String? tenantId;
  final List<AuthMethod> allowedAuthMethods;
  final List<String> dataClassificationRestrictions;
  final bool vpnOnlyMode;
  final bool allowScreenCapture;
  final int maxOfflineCacheDays;
  final bool requireBiometric;
  final bool allowFileUpload;
  final int maxFileUploadSizeMB;
}
```

### Accessibility (WCAG 2.1 AA)

**VoiceOver / TalkBack Support**
- All interactive elements have semantic labels (`Semantics` widget in Flutter)
- Custom actions for complex widgets (swipe actions on conversation list, long-press menus)
- Focus order: logical tab order, skip decorative elements
- Announcements: status changes announced via `SemanticsService.announce()`

**Visual Accessibility**
- Dynamic text sizing: respect system font size preferences (`MediaQuery.textScaleFactor`)
- Minimum touch target size: 48x48dp (Material Design guideline)
- High contrast mode: detect `MediaQuery.highContrast` and apply high contrast theme
- Color contrast: all text meets 4.5:1 contrast ratio (AA standard)
- No information conveyed by color alone (icons + labels for status indicators)

**Screen Reader Testing**
```dart
// Example: Accessible agent card
Semantics(
  label: 'Agent: ${agent.name}',
  hint: 'Double tap to open. Status: ${agent.status}',
  child: AgentCard(agent: agent),
)

// Example: Accessible execution button
Semantics(
  button: true,
  label: 'Execute agent ${agent.name}',
  enabled: canExecute,
  child: ExecuteButton(onPressed: canExecute ? () => execute(agent) : null),
)
```

**Motion and Animation**
- Respect `MediaQuery.disableAnimations` preference
- Reduce motion: disable parallax, auto-play, complex transitions
- No flashing content (epilepsy safety)

### App Distribution

**Beta Testing**
- iOS: TestFlight (internal + external testing groups)
- Android: Firebase App Distribution (internal testing tracks)
- CI/CD: GitHub Actions → build → sign → upload to TestFlight / Firebase App Distribution
- OTA updates: CodePush-compatible for non-native changes (Shorebird for Flutter)

**Enterprise Distribution**
- iOS:
  - Apple Business Manager (ABM) / Device Enrollment Program (DEP)
  - Custom B2B app distribution via Apple Business Manager
  - Enterprise Developer certificate for internal-only distribution (no App Store)
  - Managed App Configuration pushed via MDM (Jamf, Intune, VMware WS1)
- Android:
  - Android Enterprise (Managed Google Play — private app channel)
  - Direct APK distribution via enterprise MDM
  - Android Enterprise zero-touch enrollment
  - Play Integrity API for device attestation

### Core Data Models

**Agent Model (Mobile)**
```dart
class Agent {
  final String id;
  final String name;
  final String slug;
  final String? description;
  final AgentType type; // workflow, conversational, autonomous, hybrid
  final AgentStatus status; // draft, review, approved, published, deprecated
  final String ownerId;
  final String tenantId;
  final String workspaceId;
  final List<String> tags;
  final DateTime createdAt;
  final DateTime? updatedAt;
  final AgentConfig config;
}
```

**Execution Model (Mobile)**
```dart
class Execution {
  final String id;
  final String agentId;
  final String triggeredBy;
  final ExecutionStatus status; // queued, running, paused, completed, failed, cancelled
  final Map<String, dynamic> inputs;
  final Map<String, dynamic>? outputs;
  final ExecutionError? error;
  final ExecutionMetrics metrics; // duration, tokenCount, cost, model
  final List<ApprovalGate> approvalGates;
  final DateTime? startedAt;
  final DateTime? completedAt;
  final DateTime createdAt;
}

class ExecutionMetrics {
  final Duration duration;
  final int inputTokens;
  final int outputTokens;
  final double cost;
  final String model;
}
```

**Conversation Model (Mobile)**
```dart
class Conversation {
  final String id;
  final String agentId;
  final String userId;
  final String title;
  final ConversationStatus status; // active, archived, deleted
  final DateTime createdAt;
  final DateTime lastMessageAt;
  final int messageCount;
  final bool isPinned;
}

class Message {
  final String id;
  final String conversationId;
  final MessageRole role; // user, assistant, system, tool
  final String content; // Markdown content
  final List<Attachment>? attachments;
  final MessageMetadata? metadata; // tokens, cost, model, latency
  final DateTime createdAt;
  final bool isStreaming;
}
```

### Chat Interface

- Message bubbles with rich content rendering (Markdown, code syntax highlighting, LaTeX, images)
- MCP component rendering: interactive forms, data tables, charts (via `fl_chart`)
- Conversation management: create, rename, archive, search, pin
- Agent selection: browse agents, favorites, recent, search
- Typing indicators: animated dots during agent response
- Read receipts: message delivery status (sent → delivered → read)
- File sharing: documents (PDF, DOCX), images (JPEG, PNG), audio (M4A, WAV)
- Code block actions: copy, share, execute (if applicable)
- Message actions: copy, share, bookmark, report, retry
- Pull-to-refresh on conversation list
- Infinite scroll on message history (cursor-based pagination)
- Haptic feedback on interactions (iOS Taptic Engine, Android vibration)

## Output Structure

```
mobile/
├── archon_sdk/                   # Flutter SDK package
│   ├── lib/
│   │   ├── archon_sdk.dart       # Package exports
│   │   └── src/
│   │       ├── client.dart          # Archon main client
│   │       ├── auth.dart            # Authentication (biometric, SAML, OIDC)
│   │       ├── agents.dart          # Agent service (CRUD, execute, stream)
│   │       ├── models.dart          # Data models (Agent, Execution, etc.)
│   │       ├── streaming.dart       # WebSocket streaming + SSE fallback
│   │       ├── notifications.dart   # Push notification service
│   │       ├── offline.dart         # Offline queue + sync service
│   │       ├── voice.dart           # Voice input (Whisper transcription)
│   │       ├── files.dart           # File upload/download with progress
│   │       ├── config.dart          # SDK configuration
│   │       ├── secure_storage.dart  # Hardware-backed secure storage
│   │       ├── certificate_pinner.dart # TLS certificate pinning
│   │       ├── mdm.dart             # MDM managed configuration
│   │       └── exceptions.dart      # SDK-specific exceptions
│   ├── test/
│   │   ├── auth_test.dart
│   │   ├── agents_test.dart
│   │   ├── streaming_test.dart
│   │   ├── offline_test.dart
│   │   ├── secure_storage_test.dart
│   │   └── certificate_pinner_test.dart
│   ├── pubspec.yaml
│   ├── analysis_options.yaml
│   └── README.md
├── ios/                             # iOS-specific native code
│   ├── Runner/
│   │   ├── AppDelegate.swift
│   │   ├── Info.plist               # App Transport Security, URL schemes
│   │   ├── Runner.entitlements      # Keychain access, associated domains
│   │   └── Assets.xcassets/
│   ├── Runner.xcodeproj/
│   ├── ShareExtension/              # Share content to agent from any app
│   │   ├── ShareViewController.swift
│   │   └── Info.plist
│   ├── WidgetExtension/             # Home screen widgets
│   │   ├── AgentStatusWidget.swift
│   │   └── Info.plist
│   └── NotificationServiceExtension/ # Rich push notification handling
│       ├── NotificationService.swift
│       └── Info.plist
├── android/                         # Android-specific native code
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── AndroidManifest.xml
│   │   │   ├── java/.../
│   │   │   │   ├── MainActivity.kt
│   │   │   │   ├── BiometricHelper.kt
│   │   │   │   └── MDMConfigReceiver.kt
│   │   │   └── res/
│   │   │       ├── xml/
│   │   │       │   ├── network_security_config.xml  # Certificate pinning
│   │   │       │   └── app_restrictions.xml          # MDM managed config schema
│   │   │       └── values/
│   │   └── build.gradle
│   ├── app/src/main/.well-known/
│   │   └── assetlinks.json          # Digital Asset Links for App Links
│   └── build.gradle
├── lib/                             # Shared Flutter app code
│   ├── main.dart                    # App entry point
│   ├── app.dart                     # MaterialApp configuration
│   ├── router.dart                  # GoRouter navigation
│   ├── screens/
│   │   ├── auth/
│   │   │   ├── login_screen.dart    # Biometric + SSO login
│   │   │   ├── mfa_screen.dart      # MFA challenge input
│   │   │   └── sso_callback_screen.dart
│   │   ├── home/
│   │   │   ├── home_screen.dart     # Main dashboard
│   │   │   └── agent_list_screen.dart
│   │   ├── chat/
│   │   │   ├── conversation_screen.dart  # Chat interface
│   │   │   ├── conversation_list_screen.dart
│   │   │   └── message_bubble.dart
│   │   ├── execution/
│   │   │   ├── execution_detail_screen.dart
│   │   │   └── approval_screen.dart  # Human-in-loop approval
│   │   ├── profile/
│   │   │   ├── profile_screen.dart
│   │   │   └── settings_screen.dart
│   │   └── offline/
│   │       └── offline_queue_screen.dart
│   ├── widgets/
│   │   ├── rich_message.dart        # Markdown + code rendering
│   │   ├── mcp_component.dart       # MCP interactive components
│   │   ├── voice_input_button.dart  # Voice recording FAB
│   │   ├── file_upload_widget.dart  # File picker + upload progress
│   │   ├── agent_card.dart          # Agent list item
│   │   └── connectivity_banner.dart # Offline status indicator
│   ├── providers/
│   │   ├── auth_provider.dart       # Authentication state (Riverpod)
│   │   ├── agent_provider.dart      # Agent data provider
│   │   ├── chat_provider.dart       # Conversation/message state
│   │   ├── execution_provider.dart  # Execution state
│   │   ├── notification_provider.dart
│   │   ├── connectivity_provider.dart
│   │   └── theme_provider.dart      # Light/dark/high-contrast themes
│   ├── services/
│   │   ├── biometric_service.dart   # Platform biometric bridge
│   │   ├── notification_service.dart # FCM/APNs handling
│   │   ├── offline_sync_service.dart # Background sync worker
│   │   └── mdm_service.dart         # MDM config reader
│   └── utils/
│       ├── accessibility.dart       # Semantic label helpers
│       ├── constants.dart           # App-wide constants
│       └── extensions.dart          # Dart extension methods
├── test/
│   ├── screens/
│   │   ├── login_screen_test.dart
│   │   ├── conversation_screen_test.dart
│   │   └── home_screen_test.dart
│   ├── providers/
│   │   ├── auth_provider_test.dart
│   │   └── chat_provider_test.dart
│   ├── widgets/
│   │   ├── rich_message_test.dart
│   │   └── mcp_component_test.dart
│   └── integration/
│       ├── auth_flow_test.dart
│       └── offline_sync_test.dart
├── pubspec.yaml
├── analysis_options.yaml
├── Makefile                         # Dev commands (analyze, test, build)
└── README.md
```

## API Endpoints (Mobile-Relevant Subset)

```
# Authentication (consumed by SDK)
POST   /api/v1/auth/login                    # Email + password login
POST   /api/v1/auth/logout                   # Logout (revoke session + tokens)
POST   /api/v1/auth/token/refresh            # Refresh access token
GET    /api/v1/auth/oidc/authorize           # OIDC authorization redirect
GET    /api/v1/auth/oidc/callback            # OIDC callback
POST   /api/v1/auth/saml/acs                 # SAML Assertion Consumer Service
GET    /api/v1/auth/saml/login               # SP-initiated SAML login
POST   /api/v1/auth/mfa/verify              # Verify MFA code (TOTP)
GET    /api/v1/auth/sessions                 # List active sessions
DELETE /api/v1/auth/sessions/{id}            # Revoke specific session

# Mobile-specific
POST   /api/v1/mobile/devices                # Register device for push notifications
DELETE /api/v1/mobile/devices/{id}           # Unregister device
PUT    /api/v1/mobile/devices/{id}/preferences # Update notification preferences
GET    /api/v1/mobile/config                 # Get mobile app configuration (feature flags)
POST   /api/v1/mobile/certificate-pins       # Fetch latest certificate pins

# Agents
GET    /api/v1/agents                        # List agents (filtered by permissions)
GET    /api/v1/agents/{id}                   # Get agent details
POST   /api/v1/agents/{id}/execute           # Trigger execution

# Executions
GET    /api/v1/executions                    # List executions
GET    /api/v1/executions/{id}               # Get execution details
POST   /api/v1/executions/{id}/cancel        # Cancel running execution
POST   /api/v1/executions/{id}/approve-gate  # Approve human-in-loop gate

# Conversations
GET    /api/v1/conversations                 # List conversations
POST   /api/v1/conversations                 # Create conversation
GET    /api/v1/conversations/{id}            # Get conversation
PUT    /api/v1/conversations/{id}            # Update conversation (rename, archive)
DELETE /api/v1/conversations/{id}            # Delete conversation
GET    /api/v1/conversations/{id}/messages   # List messages (paginated)
POST   /api/v1/conversations/{id}/messages   # Send message

# Files
POST   /api/v1/files/upload                 # Upload file (multipart)
GET    /api/v1/files/{id}                    # Download file
GET    /api/v1/files/{id}/metadata           # Get file metadata

# Voice
POST   /api/v1/voice/transcribe             # Transcribe audio (Whisper)

# WebSocket
WS     /api/v1/ws/execution/{id}            # Stream execution events
WS     /api/v1/ws/conversation/{id}         # Stream conversation messages
```

## Verify Commands

```bash
# Flutter project analyzable
cd ~/Scripts/Archon/mobile && flutter analyze --no-fatal-infos 2>&1 | tail -1

# SDK package analyzable
cd ~/Scripts/Archon/mobile/archon_sdk && flutter analyze --no-fatal-infos 2>&1 | tail -1

# Tests pass
cd ~/Scripts/Archon/mobile && flutter test

# SDK tests pass
cd ~/Scripts/Archon/mobile/archon_sdk && flutter test

# pubspec.yaml is valid
cd ~/Scripts/Archon/mobile && flutter pub get

# SDK pubspec.yaml is valid
cd ~/Scripts/Archon/mobile/archon_sdk && flutter pub get

# iOS build succeeds (requires Xcode)
cd ~/Scripts/Archon/mobile && flutter build ios --no-codesign --debug 2>&1 | tail -5

# Android build succeeds (requires Android SDK)
cd ~/Scripts/Archon/mobile && flutter build apk --debug 2>&1 | tail -5

# Certificate pinning config exists
test -f ~/Scripts/Archon/mobile/android/app/src/main/res/xml/network_security_config.xml

# MDM restrictions schema exists
test -f ~/Scripts/Archon/mobile/android/app/src/main/res/xml/app_restrictions.xml

# Accessibility: check for Semantics widgets in all screens
grep -rn 'Semantics(' ~/Scripts/Archon/mobile/lib/screens/ | wc -l | xargs test 20 -le

# No hardcoded secrets or tokens
cd ~/Scripts/Archon/mobile && ! grep -rn 'apiKey\s*=\s*"[^"]*"' --include='*.dart' lib/ || echo 'FAIL: hardcoded secrets found'

# Secure storage used (no SharedPreferences for tokens)
cd ~/Scripts/Archon/mobile && ! grep -rn 'SharedPreferences.*token' --include='*.dart' lib/ || echo 'FAIL: insecure token storage'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Flutter SDK (`archon_sdk`) connects to backend and streams agent execution events via WebSocket
- [ ] Biometric authentication works: Face ID (iOS), fingerprint (Android), with graceful degradation
- [ ] SAML SSO flow works end-to-end: system browser → IdP login → assertion → app callback → session
- [ ] Universal Links (iOS) and App Links (Android) correctly handle SAML callback redirect
- [ ] All tokens stored in hardware-backed secure enclave (iOS Keychain / Android Keystore)
- [ ] Certificate pinning validates TLS certificates and blocks unpinned connections
- [ ] MFA challenge (TOTP) displays in-app and blocks until verified
- [ ] Push notifications received for: execution complete, approval required, alert
- [ ] File upload works with progress reporting (tested with 10MB+ file)
- [ ] Voice input records audio, transcribes via Whisper, and sends as message
- [ ] Offline mode queues requests and syncs automatically when connectivity restored
- [ ] MDM managed configuration correctly pre-populates server URL, tenant ID, auth methods
- [ ] VPN-only mode blocks API calls when VPN is disconnected
- [ ] VoiceOver (iOS) reads all interactive elements with meaningful labels
- [ ] TalkBack (Android) navigates all screens with logical focus order
- [ ] Dynamic text sizing works up to 200% without layout breakage
- [ ] High contrast mode applies to all screens
- [ ] Chat interface renders Markdown, code blocks, and MCP components correctly
- [ ] Conversation list handles 1000+ conversations with smooth scrolling (cursor pagination)
- [ ] Enterprise distribution: iOS IPA signs with enterprise certificate, Android APK installs via MDM
- [ ] No sensitive data in SharedPreferences, UserDefaults, or unencrypted local storage
- [ ] Screen capture prevention active on authentication and token display screens
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext secrets in source code, logs, or local storage
