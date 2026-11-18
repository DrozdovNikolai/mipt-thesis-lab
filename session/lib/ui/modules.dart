import 'package:flutter/material.dart';
import '../model/catalog.dart';
import '../model/document.dart';
import '../model/labels.dart';
import 'exercise_tile.dart';
import 'theme.dart';

class Modules extends StatelessWidget {
  final Document doc;
  final Json? selected;
  final ValueChanged<Json> inspect;
  final void Function(int, int, int)? move;
  const Modules(this.doc, this.selected, this.inspect, this.move, {super.key});
  @override
  Widget build(BuildContext context) => doc.modules.isEmpty
      ? const Center(child: Text('В сценарии пока нет модулей'))
      : ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final (mi, m) in doc.modules.indexed) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(2, 12, 2, 10),
                child: Wrap(
                  spacing: 12,
                  children: [
                    Text(
                      'Модуль ${mi + 1}',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 18,
                      ),
                    ),
                    Text(
                      'День ${m['dayIndex'] ?? 1}  ·  ${durationLabel(m['durationMinutes'])}',
                      style: const TextStyle(color: muted),
                    ),
                  ],
                ),
              ),
              if (doc.exercises(mi).isEmpty) const Text('Упражнений пока нет'),
              for (final (i, e) in doc.exercises(mi).indexed)
                ExerciseTile(
                  e,
                  i,
                  selected?['id'] == e['id'],
                  () => inspect(e),
                  move != null && i > 0 ? () => move!(mi, i, i - 1) : null,
                  move != null && i + 1 < doc.exercises(mi).length
                      ? () => move!(mi, i, i + 1)
                      : null,
                ),
            ],
          ],
        );
}
