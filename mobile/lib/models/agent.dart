import 'package:json_annotation/json_annotation.dart';

part 'agent.g.dart';

/// Represents an Archon AI agent.
@JsonSerializable()
class Agent {
  const Agent({
    required this.id,
    required this.name,
    required this.description,
    required this.status,
    this.model,
    this.systemPrompt,
    this.createdAt,
    this.updatedAt,
  });

  factory Agent.fromJson(Map<String, dynamic> json) => _$AgentFromJson(json);

  final String id;
  final String name;
  final String description;
  final AgentStatus status;
  final String? model;

  @JsonKey(name: 'system_prompt')
  final String? systemPrompt;

  @JsonKey(name: 'created_at')
  final DateTime? createdAt;

  @JsonKey(name: 'updated_at')
  final DateTime? updatedAt;

  Map<String, dynamic> toJson() => _$AgentToJson(this);
}

enum AgentStatus {
  @JsonValue('active')
  active,

  @JsonValue('inactive')
  inactive,

  @JsonValue('error')
  error,
}
