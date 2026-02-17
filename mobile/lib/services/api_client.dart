import 'dart:convert';
import 'package:http/http.dart' as http;

import '../models/agent.dart';

/// API envelope response matching Archon backend contract.
class ApiResponse<T> {
  const ApiResponse({required this.data, this.meta});

  final T data;
  final Map<String, dynamic>? meta;
}

/// HTTP client for the Archon REST API.
class ApiClient {
  ApiClient({required this.baseUrl, http.Client? httpClient})
      : _client = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      };

  String? _authToken;

  /// Sets the JWT bearer token for authenticated requests.
  void setAuthToken(String token) {
    _authToken = token;
  }

  Map<String, String> get _authHeaders => {
        ..._headers,
        if (_authToken != null) 'Authorization': 'Bearer $_authToken',
      };

  /// GET /agents — paginated list.
  Future<ApiResponse<List<Agent>>> getAgents({
    int limit = 20,
    int offset = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/agents?limit=$limit&offset=$offset');
    final response = await _client.get(uri, headers: _authHeaders);
    _assertSuccess(response);

    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final items = (body['data'] as List<dynamic>)
        .map((e) => Agent.fromJson(e as Map<String, dynamic>))
        .toList();

    return ApiResponse(
      data: items,
      meta: body['meta'] as Map<String, dynamic>?,
    );
  }

  /// GET /agents/:id
  Future<ApiResponse<Agent>> getAgent(String id) async {
    final uri = Uri.parse('$baseUrl/agents/$id');
    final response = await _client.get(uri, headers: _authHeaders);
    _assertSuccess(response);

    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final agent = Agent.fromJson(body['data'] as Map<String, dynamic>);

    return ApiResponse(
      data: agent,
      meta: body['meta'] as Map<String, dynamic>?,
    );
  }

  /// Health check — unauthenticated.
  Future<bool> healthCheck() async {
    try {
      final uri = Uri.parse('$baseUrl/health');
      final response = await _client.get(uri, headers: _headers);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  void _assertSuccess(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        statusCode: response.statusCode,
        message: _extractErrorMessage(response),
      );
    }
  }

  String _extractErrorMessage(http.Response response) {
    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final errors = body['errors'] as List<dynamic>?;
      if (errors != null && errors.isNotEmpty) {
        final first = errors.first as Map<String, dynamic>;
        return first['message'] as String? ?? 'Unknown error';
      }
    } catch (_) {
      // fall through
    }
    return 'HTTP ${response.statusCode}';
  }

  /// Release underlying HTTP resources.
  void dispose() {
    _client.close();
  }
}

class ApiException implements Exception {
  const ApiException({required this.statusCode, required this.message});

  final int statusCode;
  final String message;

  @override
  String toString() => 'ApiException($statusCode): $message';
}
