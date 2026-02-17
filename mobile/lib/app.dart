import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'screens/home_screen.dart';
import 'screens/agent_list_screen.dart';
import 'screens/agent_detail_screen.dart';

final GoRouter _router = GoRouter(
  initialLocation: '/',
  routes: <RouteBase>[
    GoRoute(
      path: '/',
      builder: (BuildContext context, GoRouterState state) =>
          const HomeScreen(),
    ),
    GoRoute(
      path: '/agents',
      builder: (BuildContext context, GoRouterState state) =>
          const AgentListScreen(),
    ),
    GoRoute(
      path: '/agents/:id',
      builder: (BuildContext context, GoRouterState state) {
        final agentId = state.pathParameters['id']!;
        return AgentDetailScreen(agentId: agentId);
      },
    ),
  ],
);

class ArchonApp extends StatelessWidget {
  const ArchonApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'Archon',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: Colors.deepPurple,
        useMaterial3: true,
        brightness: Brightness.light,
      ),
      darkTheme: ThemeData(
        colorSchemeSeed: Colors.deepPurple,
        useMaterial3: true,
        brightness: Brightness.dark,
      ),
      themeMode: ThemeMode.system,
      routerConfig: _router,
    );
  }
}
