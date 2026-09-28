class ApiFailure implements Exception {
  final int status;
  final String message;
  ApiFailure(this.status, this.message);
  factory ApiFailure.from(int status, dynamic body) {
    final error = body is Map ? body['error'] : null;
    final message = error is Map ? error['message'] : null;
    return ApiFailure(
      status,
      message?.toString() ?? 'Ошибка сервера ($status)',
    );
  }
  @override
  String toString() => message;
}
