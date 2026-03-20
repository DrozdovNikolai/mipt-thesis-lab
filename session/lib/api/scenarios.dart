import 'dart:math';
import '../model/catalog.dart';
import 'client.dart';

class Scenarios {
  final SessionApi api;
  final editorId=List.generate(16,(_)=>Random.secure().nextInt(256).toRadixString(16).padLeft(2,'0')).join();
  Scenarios(this.api);
  static const path='/training/scenarios';
  static const pageSize=24;
  Future<CatalogPage> list(String search,int offset) async=>CatalogPage.from(await api.request('GET','$path/summary',query:{
    'offset':'$offset','limit':'$pageSize',if(search.trim().isNotEmpty)'q':search.trim()
  }));
}
