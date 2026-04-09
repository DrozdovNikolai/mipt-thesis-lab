import 'dart:convert';
import 'catalog.dart';

List<Json> ordered(dynamic value) {
  final rows=List<Json>.from(value as List);
  return rows..sort((a,b){
    final c=(a['orderIndex'] as int).compareTo(b['orderIndex'] as int);
    return c==0?(a['id'] as int).compareTo(b['id'] as int):c;
  });
}
Json pick(Json data,List<String> fields)=>{for(final name in fields) if(data.containsKey(name))name:data[name]};
