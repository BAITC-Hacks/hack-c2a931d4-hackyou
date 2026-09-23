"""Community hypotheses grounded in observed aggregate flows and role composition."""

from collections import Counter, defaultdict

CLUSTER_HYPOTHESIS_VERSION = 2


def describe_communities(clusters, ordered_nodes, graph):
    """Annotate new analyses; never called while restoring an existing snapshot."""
    members = defaultdict(list)
    membership = {}
    for node in ordered_nodes:
        members[node["cluster_id"]].append(node)
        membership[node["gid"]] = node["cluster_id"]
    totals = defaultdict(lambda: {"internal": 0, "external_in": 0, "external_out": 0})
    for src, dst, edge in graph.edges(data=True):
        source, target = membership[src], membership[dst]
        amount = int(edge["sum_tiyn"])
        if source == target:
            totals[source]["internal"] += amount
        else:
            totals[source]["external_out"] += amount
            totals[target]["external_in"] += amount
    for cluster in clusters:
        nodes = members[cluster["cluster_id"]]
        flows = totals[cluster["cluster_id"]]
        roles = dict(sorted(Counter(node["role"] for node in nodes).items()))
        seed_count = sum(bool(node["is_seed"]) for node in nodes)
        boundary_count = sum(bool(node["truncated_by_depth"]) for node in nodes)
        incoming, outgoing = flows["external_in"], flows["external_out"]
        if incoming and outgoing:
            pattern = "Гипотеза: сообщество участвует во входящем и исходящем обмене с другими сообществами"
        elif incoming:
            pattern = "Гипотеза: сообщество принимает наблюдаемые переводы извне без наблюдаемого выхода за его пределы"
        elif outgoing:
            pattern = "Гипотеза: сообщество отправляет наблюдаемые переводы другим сообществам"
        elif flows["internal"]:
            pattern = "Гипотеза: в выборке наблюдается локальная группа внутренних переводов"
        else:
            pattern = "Недостаточно наблюдаемых денежных потоков для функциональной гипотезы"
        composition = ", ".join(f"{role}: {count}" for role, count in roles.items())
        text = (
            f"{pattern}. Состав ролей: {composition}. "
            f"Внутри: {flows['internal'] / 100:.2f} KZT; "
            f"внешний вход: {incoming / 100:.2f} KZT; внешний выход: {outgoing / 100:.2f} KZT. "
            f"Seed: {seed_count}; узлов на границе наблюдения: {boundary_count}."
        )
        if seed_count > 1:
            text += " Несколько seed находятся в одной группе; это не доказывает их координацию."
        if seed_count or boundary_count:
            text += " Неполные входы seed и граница обхода ограничивают выводы о балансе группы."
        text += " Агрегаты не устанавливают происхождение одних и тех же средств или виновность."
        cluster.update(
            top_gids=[node["gid"] for node in nodes[:5]],
            hypothesis=text,
            hypothesis_metrics={
                "role_counts": roles, "n_seed": seed_count, "n_boundary": boundary_count,
                "internal_tiyn": flows["internal"], "external_in_tiyn": incoming,
                "external_out_tiyn": outgoing,
            },
        )
