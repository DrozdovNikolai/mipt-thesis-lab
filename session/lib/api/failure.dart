class ApiFailure implements Exception {
  final int status;
  final String message;
  ApiFailure(this.status, this.message);
  factory ApiFailure.from(int status, dynamic body) {
    final detail = body is Map ? body['detail'] ?? body : body;
    final error = detail is Map ? detail['error'] ?? detail : detail;
    final message = error is Map
        ? error['message']
        : error is String
        ? error
        : null;
    return ApiFailure(
      status,
      message?.toString() ?? 'Ошибка сервера ($status)',
    );
  }
  @override
  String toString() => message;
}
