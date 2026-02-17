import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';
import 'package:provider/provider.dart';

import 'app.dart';
import 'services/api_client.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Hive.initFlutter();

  final apiClient = ApiClient(baseUrl: const String.fromEnvironment(
    'ARCHON_API_URL',
    defaultValue: 'http://localhost:8000/api/v1',
  ));

  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: apiClient),
      ],
      child: const ArchonApp(),
    ),
  );
}
