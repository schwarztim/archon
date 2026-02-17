import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../models/agent.dart';
import '../services/api_client.dart';

/// Displays a paginated list of Archon agents.
class AgentListScreen extends StatefulWidget {
  const AgentListScreen({super.key});

  @override
  State<AgentListScreen> createState() => _AgentListScreenState();
}

class _AgentListScreenState extends State<AgentListScreen> {
  List<Agent> _agents = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadAgents();
  }

  Future<void> _loadAgents() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final apiClient = context.read<ApiClient>();
      final response = await apiClient.getAgents();
      if (!mounted) return;
      setState(() {
        _agents = response.data;
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
        _error = 'Failed to load agents';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Agents'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadAgents,
          ),
        ],
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
              onPressed: _loadAgents,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_agents.isEmpty) {
      return const Center(child: Text('No agents found.'));
    }

    return RefreshIndicator(
      onRefresh: _loadAgents,
      child: ListView.builder(
        itemCount: _agents.length,
        itemBuilder: (context, index) {
          final agent = _agents[index];
          return _AgentTile(agent: agent);
        },
      ),
    );
  }
}

class _AgentTile extends StatelessWidget {
  const _AgentTile({required this.agent});

  final Agent agent;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: _statusColor(agent.status, theme),
        child: const Icon(Icons.smart_toy_outlined, size: 20),
      ),
      title: Text(agent.name),
      subtitle: Text(
        agent.description,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: const Icon(Icons.chevron_right),
      onTap: () => context.go('/agents/${agent.id}'),
    );
  }

  Color _statusColor(AgentStatus status, ThemeData theme) {
    switch (status) {
      case AgentStatus.active:
        return Colors.green;
      case AgentStatus.inactive:
        return theme.colorScheme.surfaceVariant;
      case AgentStatus.error:
        return theme.colorScheme.error;
    }
  }
}
