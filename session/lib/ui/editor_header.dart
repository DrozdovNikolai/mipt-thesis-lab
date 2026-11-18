import 'package:flutter/material.dart';
import '../model/document.dart';
import '../model/labels.dart';
import 'theme.dart';

class EditorHeader extends StatelessWidget {
  final Document doc;
  final bool saving;
  final VoidCallback? save;
  final VoidCallback reload;
  const EditorHeader(
    this.doc,
    this.saving,
    this.save,
    this.reload, {
    super.key,
  });
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(16),
    color: panel,
    child: Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 20,
      runSpacing: 8,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              doc.data['title'],
              style: Theme.of(context).textTheme.titleLarge,
            ),
            Text(
              '${statusLabel(doc.data['status'] ?? '')}  ·  Версия ${doc.version}${doc.dirty ? '  ·  Есть изменения' : ''}',
              style: const TextStyle(color: muted),
            ),
          ],
        ),
        Wrap(
          children: [
            IconButton(
              tooltip: 'Загрузить с сервера',
              onPressed: saving ? null : reload,
              icon: const Icon(Icons.refresh),
            ),
            FilledButton.icon(
              onPressed: save,
              icon: const Icon(Icons.save_outlined),
              label: Text(saving ? 'Сохранение…' : 'Сохранить'),
            ),
          ],
        ),
      ],
    ),
  );
}
