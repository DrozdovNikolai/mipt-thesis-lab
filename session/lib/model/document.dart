import 'dart:convert';
import 'catalog.dart';

List<Json> ordered(dynamic value) {
  final rows = List<Json>.from(value as List);
  return rows..sort((a, b) {
    final c = (a['orderIndex'] as int).compareTo(b['orderIndex'] as int);
    return c == 0 ? (a['id'] as int).compareTo(b['id'] as int) : c;
  });
}

Json pick(Json data, List<String> fields) => {
  for (final name in fields)
    if (data.containsKey(name)) name: data[name],
};
Json elementSnapshot(Json data) => pick(data, [
  'elementId',
  'orderIndex',
  'details',
  'startingHeight',
  'endingHeight',
  'profileType',
]);
Json? paramSnapshot(Json? value) {
  if (value == null) return null;
  final payload = pick(value, [
    'intensity',
    'zfwT',
    'guidanceDoc',
    'guidancePlainText',
    'originalTl',
    'destinationTl',
  ]);
  for (final key in ['originalTl', 'destinationTl']) {
    if (payload[key] is Map) {
      payload[key] = Map<String, dynamic>.from(payload[key])..remove('id');
    }
  }
  return payload;
}

Json exerciseSnapshot(Json data, int position) => {
  ...pick(data, [
    'id',
    'clientUid',
    'moduleId',
    'kind',
    'durationMinutes',
    'crewMemberNumber',
  ]),
  'orderIndex': position,
  'competenceIds': [for (final c in data['competences'] as List) c['id']],
  'elements': [for (final e in data['elements'] as List) elementSnapshot(e)],
  'params': paramSnapshot(data['params']),
};

class Document {
  final Json data;
  late final List<Json> modules;
  late int version;
  late final Map<int, List<int>> _positions;
  Document(this.data) {
    version = data['contentVersion'] as int;
    modules = [
      for (final m in ordered(data['modules']))
        {...m, 'exercises': ordered(m['exercises'])},
    ];
    // Capture slots before any move, including non-contiguous legacy indices.
    _positions = {
      for (final m in modules)
        m['id'] as int: [
          for (final e in m['exercises']) e['orderIndex'] as int,
        ],
    };
    markClean();
  }
  List<Json> exercises(int module) =>
      modules[module]['exercises'] as List<Json>;
  void move(int module, int from, int to) {
    final rows = exercises(module);
    if (from < 0 ||
        from >= rows.length ||
        to < 0 ||
        to >= rows.length ||
        from == to) {
      return;
    }
    rows.insert(to, rows.removeAt(from));
  }

  Json snapshot() => {
    'modules': [
      for (final m in modules)
        {
          ...pick(m, [
            'id',
            'clientUid',
            'scenarioId',
            'orderIndex',
            'dayIndex',
            'dayStart',
            'durationMinutes',
            'contentSubcolumnId',
          ]),
          'exercises': [
            for (final (index, e) in (m['exercises'] as List<Json>).indexed)
              exerciseSnapshot(e, _positions[m['id']]![index]),
          ],
        },
    ],
  };
  late String _baseline;
  String orderSignature() => jsonEncode([
    for (final m in modules) [for (final e in m['exercises']) e['id']],
  ]);
  void markClean() {
    _baseline = orderSignature();
  }

  bool get dirty => _baseline != orderSignature();
}
