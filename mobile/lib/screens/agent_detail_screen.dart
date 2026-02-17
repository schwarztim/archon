import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/agent.dart';
import '../services/api_client.dart';

/// Shows details for a single Archon agent.
class AgentDetailScreen extends StatefulWidget {
  const AgentDetailScreen({super.key, required this.agentId});

  final String agentId;

  @override
  State<AgentDetailScreen> createState() => _AgentDetailScreenState();
}

class _AgentDetailScreenState extends State<AgentDetailScreen> {
  Agent? _agent;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadAgent();
  }

  Future<void> _loadAgent() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final apiClient = context.read<ApiClient>();
      final response = await apiClient.getAgent(widget.agentId);
      if (!mounted) return;
      setState(() {
        _agent = response.data;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to load agent';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_agent?.name ?? 'Agent'),
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.error_outline,
                size: 48, color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 16),
            Text(_error!, style: Theme.of(context).textTheme.bodyLarge),
            const SizedBox(height: 16),
            FilledButton.tonal(
              onPressed: _loadAgent,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    final agent = _agent;
    if (agent == null) {
      return const Center(child: Text('Agent not found.'));
    }

    final theme = Theme.of(context);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Status chip
          Row(
            children: [
              _StatusChip(status: agent.status),
              const Spacer(),
              if (agent.model != null)
                Chip(label: Text(agent.model!)),
            ],
          ),
          const SizedBox(height: 24),

          // Description
          Text('Description', style: theme.textTheme.titleSmall),
          const SizedBox(height: 8),
          Text(agent.description, style: theme.textTheme.bodyLarge),
          const SizedBox(height: 24),

          // System prompt
          if (agent.systemPrompt != null) ...[
            Text('System Prompt', style: theme.textTheme.titleSmall),
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceVariant,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                agent.systemPrompt!,
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontFamily: 'monospace',
                ),
              ),
            ),
            const SizedBox(height: 24),
          ],

          // Metadata
          if (agent.createdAt != null)
            _MetadataRow(label: 'Created', value: agent.createdAt.toString()),
          if (agent.updatedAt != null)
            _MetadataRow(label: 'Updated', value: agent.updatedAt.toString()),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});

  final AgentStatus status;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      AgentStatus.active => ('Active', Colors.green),
      AgentStatus.inactive => ('Inactive', Colors.grey),
      AgentStatus.error => ('Error', Theme.of(context).colorScheme.error),
    };

    return Chip(
      avatar: CircleAvatar(
        backgroundColor: color,
        radius: 6,
      ),
      label: Text(label),
    );
  }
}

class _MetadataRow extends StatelessWidget {
  const _MetadataRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
