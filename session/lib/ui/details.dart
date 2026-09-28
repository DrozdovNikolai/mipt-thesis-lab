import 'package:flutter/material.dart';
import '../model/catalog.dart';
import '../model/labels.dart';
import 'theme.dart';

class Details extends StatelessWidget {
  final Json exercise;
  const Details(this.exercise, {super.key});
  @override
  Widget build(BuildContext context) {
    final e = exercise;
    final params = e['params'] as Map?;
    final rows = <String, String>{
      'Тип': exerciseLabel(e['kind']),
      'Длительность': durationLabel(e['durationMinutes']),
      if (e['crewMemberNumber'] != null)
        'Член экипажа': "${e['crewMemberNumber']}",
      if (params?['intensity'] != null)
        'Интенсивность': params!['intensity'].toString(),
      if (params?['guidancePlainText'] != null)
        'Инструкции': params!['guidancePlainText'].toString(),
      if ((e['competences'] as List).isNotEmpty)
        'Компетенции': [
          for (final c in e['competences']) c['code'],
        ].join(' · '),
    };
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          'Параметры упражнения',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const Divider(height: 28),
        for (final entry in rows.entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  entry.key,
                  style: const TextStyle(color: muted, fontSize: 12),
                ),
                const SizedBox(height: 3),
                SelectableText(entry.value),
              ],
            ),
          ),
        for (final el in e['elements'])
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('Элемент №${el['elementId']}'),
            subtitle: el['details'] == null ? null : Text(el['details']),
          ),
      ],
    );
  }
}
