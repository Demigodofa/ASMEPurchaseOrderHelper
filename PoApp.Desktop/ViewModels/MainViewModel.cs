using System.Collections.ObjectModel;
using System.Linq;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PoApp.Core.Models;
using PoApp.Desktop.Services;

namespace PoApp.Desktop.ViewModels;

public partial class MainViewModel : ObservableObject
{
    public ObservableCollection<MaterialSpecRecord> Specs { get; } = new();
    public ObservableCollection<string> SpecTypes { get; } = new() { "", "SA", "A" };
    public ObservableCollection<string> AvailableGrades { get; } = new();
    public ObservableCollection<OrderingOption> OrderingOptions { get; } = new();

    [ObservableProperty] private string? selectedSpecType;
    [ObservableProperty] private MaterialSpecRecord? selectedSpec;
    [ObservableProperty] private string? selectedGrade;
    [ObservableProperty] private string astmDisplay = "";
    [ObservableProperty] private string generatedText = "";

    public MainViewModel()
    {
        var dataset = JsonMaterialRepository.LoadFromRepoDataFolder();

        foreach (var m in dataset.Materials.OrderBy(m => m.SpecDesignation))
            Specs.Add(m);

        if (Specs.Count > 0)
            SelectedSpec = Specs[0];
    }

    partial void OnSelectedSpecChanged(MaterialSpecRecord? value)
    {
        AvailableGrades.Clear();
        OrderingOptions.Clear();

        if (value is null)
        {
            AstmDisplay = "";
            SelectedGrade = null;
            GeneratedText = "";
            return;
        }

        AstmDisplay = $"{value.AstmSpec}-{value.AstmYear}";

        foreach (var g in value.Grades ?? [])
            AvailableGrades.Add(g);

 


       SelectedGrade = AvailableGrades.FirstOrDefault();

        foreach (var note in value.OrderingNotes ?? [])
            OrderingOptions.Add(new OrderingOption(note, isSelected: true));

        Regenerate();
    }

    partial void OnSelectedGradeChanged(string? value)
    {
        Regenerate();
    }

    partial void OnSelectedSpecTypeChanged(string? value)
    {
        Regenerate();
    }

    [RelayCommand]
private void ToggleAllOrdering(object? parameter)
{
    // WPF often passes CommandParameter as string ("True"/"False")
    bool selectAll =
        parameter is bool b ? b :
        bool.TryParse(parameter?.ToString(), out var parsed) && parsed;

    foreach (var opt in OrderingOptions)
        opt.IsSelected = selectAll;

    Regenerate();
}
[RelayCommand]
    private void SelectAllOrdering()
    {
        foreach (var opt in OrderingOptions)
            opt.IsSelected = true;

        Regenerate();
    }

    [RelayCommand]
    private void SelectNoneOrdering()
    {
        foreach (var opt in OrderingOptions)
            opt.IsSelected = false;

        Regenerate();
    }
[RelayCommand]
    private void CopyToClipboard()
    {
        if (!string.IsNullOrWhiteSpace(GeneratedText))
            Clipboard.SetText(GeneratedText);
    }













    [RelayCommand]
    private void Regenerate()
    {
        if (SelectedSpec is null)
        {
            GeneratedText = "";
            return;
        }

 









       var selectedNotes = OrderingOptions.Where(o => o.IsSelected).Select(o => o.Text);
        GeneratedText = PoTextGenerator.Generate(SelectedSpec, SelectedGrade, selectedNotes, SelectedSpecType);
    }
}

public sealed partial class OrderingOption : ObservableObject
{
 






   public OrderingOption(string text, bool isSelected)
    {
        Text = text;
        IsSelected = isSelected;
    }

    public string Text { get; }







    [ObservableProperty]
    private bool isSelected;
}

