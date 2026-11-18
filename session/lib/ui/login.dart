import 'package:flutter/material.dart';
import 'brand.dart';
import 'theme.dart';
import 'feedback.dart';

class Login extends StatefulWidget {
  final Future<void> Function(String, String) authenticate;
  const Login(this.authenticate, {super.key});
  @override
  State<Login> createState() => _LoginState();
}

class _LoginState extends State<Login> {
  final account = TextEditingController(), password = TextEditingController();
  bool obscure = true, working = false;
  String? error;
  @override
  void dispose() {
    account.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (working) return;
    if (account.text.trim().isEmpty || password.text.isEmpty) {
      setState(() => error = 'Введите логин и пароль.');
      return;
    }
    setState(() {
      working = true;
      error = null;
    });
    try {
      await widget.authenticate(account.text.trim(), password.text);
    } catch (e) {
      if (mounted) setState(() => error = errorText(e));
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Container(
          constraints: const BoxConstraints(maxWidth: 390),
          padding: const EdgeInsets.all(28),
          decoration: BoxDecoration(
            color: panel,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: line),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Brand(),
              const SizedBox(height: 32),
              Text(
                'Вход в редактор',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 20),
              TextField(
                controller: account,
                enabled: !working,
                autofillHints: const [AutofillHints.username],
                decoration: const InputDecoration(labelText: 'Логин'),
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 14),
              TextField(
                controller: password,
                enabled: !working,
                obscureText: obscure,
                onSubmitted: (_) => submit(),
                autofillHints: const [AutofillHints.password],
                decoration: InputDecoration(
                  labelText: 'Пароль',
                  suffixIcon: IconButton(
                    tooltip: obscure ? 'Показать пароль' : 'Скрыть пароль',
                    onPressed: () => setState(() => obscure = !obscure),
                    icon: Icon(
                      obscure
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
              ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: working ? null : submit,
                child: Text(working ? 'Вход…' : 'Войти'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
