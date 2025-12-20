from textual.widgets import DataTable
print([x for x in dir(DataTable) if 'coord' in x or 'get_' in x or 'click' in x])
