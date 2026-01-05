using System.Windows;
using PoApp.Desktop.ViewModels;

namespace PoApp.Desktop;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        DataContext = new MainViewModel();
    }
}