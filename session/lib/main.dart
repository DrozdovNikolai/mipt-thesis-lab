import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'api/client.dart';
import 'api/profile.dart';
import 'api/scenarios.dart';
import 'ui/login.dart';
import 'ui/theme.dart';
import 'ui/workspace.dart';

void main() => runApp(const SessionApp());

class SessionApp extends StatefulWidget {
  const SessionApp({super.key});
  @override
  State<SessionApp> createState() => _SessionAppState();
}

class _SessionAppState extends State<SessionApp> {
  final client = http.Client();
  late final api = SessionApi(client);
  late final scenarios = Scenarios(api);
  Profile? profile;
  Future<void> login(String name, String password) async {
    await api.login(name, password);
    try {
      final next = Profile.from(await api.request('GET', '/auth/me'));
      if (mounted) setState(() => profile = next);
    } catch (_) {
      api.logout();
      rethrow;
    }
  }

  void logout() {
    api.logout();
    setState(() => profile = null);
  }

  @override
  void dispose() {
    client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '55NORD Session',
    theme: sessionTheme(),
    debugShowCheckedModeBanner: false,
    home: profile == null
        ? Login(login)
        : Workspace(profile!, scenarios, logout),
  );
}
