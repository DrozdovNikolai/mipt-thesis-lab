Uri apiUri(String path, [Map<String,String>? query]) {
  const configured = String.fromEnvironment('API_BASE_URL');
  final local = ['127.0.0.1', 'localhost'].contains(Uri.base.host);
  final base = configured.isNotEmpty ? configured : local ? 'http://127.0.0.1:8812/api' : '/api';
  return Uri.base.resolve('${base.replaceFirst(RegExp(r'/+$'), '')}$path').replace(queryParameters: query);
}
