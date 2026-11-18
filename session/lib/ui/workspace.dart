import 'package:flutter/material.dart';
import '../api/profile.dart';
import '../api/scenarios.dart';
import '../model/catalog.dart';
import '../model/document.dart';
import 'brand.dart';
import 'details.dart';
import 'discard.dart';
import 'editor_header.dart';
import 'feedback.dart';
import 'library.dart';
import 'modules.dart';
import 'theme.dart';

class Workspace extends StatefulWidget {
  final Profile profile;
  final Scenarios api;
  final VoidCallback logout;
  const Workspace(this.profile, this.api, this.logout, {super.key});
  @override
  State<Workspace> createState() => _WorkspaceState();
}

class _WorkspaceState extends State<Workspace> {
  Document? doc;
  Json? selected;
  bool busy = false;
  bool saving = false;
  bool get editable =>
      widget.profile.canEdit &&
      doc?.data['status']?.toString().toUpperCase() == 'DRAFT';
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) {
      final compact = box.maxWidth < 820, wide = box.maxWidth >= 1200;
      Widget library(bool drawer) =>
          Library(widget.api, doc?.data['id'], (item) {
            if (drawer) Navigator.pop(context);
            open(item.id);
          });
      return Scaffold(
        appBar: AppBar(
          title: const Brand(),
          backgroundColor: panel,
          actions: [
            if (!compact) Text(widget.profile.name),
            IconButton(
              tooltip: 'Выйти',
              onPressed: busy || saving
                  ? null
                  : () async {
                      if (await canLeave() && mounted) widget.logout();
                    },
              icon: const Icon(Icons.logout),
            ),
          ],
        ),
        drawer: compact ? Drawer(child: SafeArea(child: library(true))) : null,
        body: Row(
          children: [
            if (!compact) ...[
              SizedBox(width: 285, child: library(false)),
              const VerticalDivider(width: 1),
            ],
            Expanded(child: editor(wide)),
          ],
        ),
      );
    },
  );
  Future<bool> canLeave() async =>
      doc?.dirty != true || await confirmDiscard(context);
  Future<void> open(int id) async {
    if (busy || saving) return;
    if (!await canLeave() || !mounted || busy || saving) return;
    setState(() => busy = true);
    try {
      final next = Document(await widget.api.open(id))..markClean();
      if (mounted) {
        setState(() {
          doc = next;
          selected = null;
        });
      }
    } catch (e) {
      if (mounted) notify(context, errorText(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save() async {
    final current = doc;
    if (current == null || !editable || busy || saving || !current.dirty) {
      return;
    }
    setState(() => saving = true);
    try {
      final version = await widget.api.save(
        current.data['id'],
        current.version,
        current.snapshot(),
      );
      current.version = version;
      current.markClean();
      try {
        await widget.api.release(current.data['id']);
      } catch (_) {
        /* An unreleased lease expires on the server. */
      }
      if (mounted) notify(context, 'Порядок упражнений сохранён.');
    } catch (e) {
      if (mounted) notify(context, errorText(e));
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  void inspect(Json exercise, bool wide) {
    setState(() => selected = exercise);
    if (!wide) {
      showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (_) => Details(exercise),
      );
    }
  }

  Widget editor(bool wide) {
    if (busy) return const Center(child: CircularProgressIndicator());
    final current = doc;
    if (current == null) {
      return const Center(child: Text('Выберите сценарий в каталоге'));
    }
    return Column(
      children: [
        SizedBox(
          width: double.infinity,
          child: EditorHeader(
            current,
            saving,
            editable && current.dirty && !saving ? save : null,
            () => open(current.data['id']),
          ),
        ),
        Expanded(
          child: Row(
            children: [
              Expanded(
                child: Modules(
                  current,
                  selected,
                  (e) => inspect(e, wide),
                  editable && !saving
                      ? (m, a, b) => setState(() => current.move(m, a, b))
                      : null,
                ),
              ),
              if (wide) ...[
                const VerticalDivider(width: 1),
                SizedBox(
                  width: 245,
                  child: ColoredBox(
                    color: panel,
                    child: selected == null
                        ? const Center(child: Text('Выберите упражнение'))
                        : Details(selected!),
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
