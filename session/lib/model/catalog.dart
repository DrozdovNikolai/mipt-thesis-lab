typedef Json = Map<String,dynamic>;
class CatalogItem {
  final Json data;
  CatalogItem(this.data);
  int get id=>data['id'] as int;
  String get title=>data['title'] as String;
  String get aircraft=>data['aircraftCode']?.toString() ?? 'ВС №${data['aircraftId']}';
  String get status=>data['status']?.toString() ?? '';
  int get modules=>data['modulesCount'] as int? ?? 0;
  int get minutes=>data['durationTotalMinutes'] as int? ?? 0;
}
class CatalogPage {
  final int total;
  final List<CatalogItem> items;
  CatalogPage(this.total,this.items);
  factory CatalogPage.from(Json data)=>CatalogPage(data['total'] as int,[for(final row in data['items']) CatalogItem(row)]);
}
